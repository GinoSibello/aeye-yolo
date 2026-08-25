"""Instrumentacion de rendimiento sin alterar el pipeline de AEYE."""

import json
import statistics
import time
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path


TIMING_KEYS = (
    "schedule_lag_ms",
    "frame_age_ms",
    "preprocess_ms",
    "inference_ms",
    "postprocess_ms",
    "detector_total_ms",
    "tracker_ms",
    "capture_to_result_ms",
)


def _percentile(values, percentile):
    """Calcula un percentil lineal sobre una secuencia numerica."""
    ordered = sorted(values)
    if not ordered:
        return None
    position = (len(ordered) - 1) * float(percentile)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _timing_summary(values):
    """Resume una ventana de duraciones en milisegundos."""
    rows = list(values)
    if not rows:
        return {"samples": 0, "avg": None, "p50": None, "p95": None, "max": None}
    return {
        "samples": len(rows),
        "avg": round(statistics.fmean(rows), 3),
        "p50": round(_percentile(rows, 0.50), 3),
        "p95": round(_percentile(rows, 0.95), 3),
        "max": round(max(rows), 3),
    }


class PerformanceMonitor:
    """Acumula contadores y latencias para una ejecucion reproducible."""

    def __init__(self, camera_ids, max_timing_samples=50000):
        self.started_monotonic = time.monotonic()
        self.started_at = datetime.now().astimezone()
        self.max_timing_samples = max(1000, int(max_timing_samples))
        self.ended_monotonic = None
        self.ended_at = None
        self.rows = {}
        for camera_id in camera_ids:
            self.rows[camera_id] = self._new_row()

    def _new_row(self):
        return {
            "analysis_attempts": 0,
            "analyzed_frames": 0,
            "unique_analyzed_frames": 0,
            "duplicate_analyses": 0,
            "scheduler_skipped_frames": 0,
            "no_data_cycles": 0,
            "processing_errors": 0,
            "last_sequence": None,
            "timings": {
                key: deque(maxlen=self.max_timing_samples) for key in TIMING_KEYS
            },
        }

    def stop(self):
        """Congela el final de la ventana antes de esperar cierres externos."""
        if self.ended_monotonic is None:
            self.ended_monotonic = time.monotonic()
            self.ended_at = datetime.now().astimezone()

    def _duration(self):
        """Devuelve la duracion activa, excluyendo el cierre de recursos."""
        endpoint = self.ended_monotonic or time.monotonic()

        return max(endpoint - self.started_monotonic, 1e-9)
    def record_no_data(self, camera_id):
        """Cuenta un turno de inferencia sin frame valido."""
        row = self.rows[camera_id]
        row["analysis_attempts"] += 1
        row["no_data_cycles"] += 1

    def record_error(self, camera_id):
        """Cuenta un fallo durante deteccion o tracking."""
        row = self.rows[camera_id]
        row["analysis_attempts"] += 1
        row["processing_errors"] += 1

    def record_analysis(self, camera_id, sequence, timings):
        """Registra un resultado valido y devuelve estadisticas acumuladas breves."""
        row = self.rows[camera_id]
        row["analysis_attempts"] += 1
        row["analyzed_frames"] += 1

        previous = row["last_sequence"]
        if previous is None or sequence != previous:
            row["unique_analyzed_frames"] += 1
            if previous is not None and sequence > previous + 1:
                row["scheduler_skipped_frames"] += sequence - previous - 1
        else:
            row["duplicate_analyses"] += 1
        row["last_sequence"] = int(sequence)

        for key in TIMING_KEYS:
            value = timings.get(key)
            if isinstance(value, (int, float)):
                row["timings"][key].append(float(value))
        return self.camera_snapshot(camera_id)

    def camera_snapshot(self, camera_id):
        """Devuelve contadores y ultimos percentiles sin datos sensibles."""
        row = self.rows[camera_id]
        duration = self._duration()
        return {
            "analyzed_fps": round(row["analyzed_frames"] / duration, 3),
            "analyzed_frames": row["analyzed_frames"],
            "scheduler_skipped_frames": row["scheduler_skipped_frames"],
            "duplicate_analyses": row["duplicate_analyses"],
            "no_data_cycles": row["no_data_cycles"],
            "processing_errors": row["processing_errors"],
        }

    def summary(self, readers, configuration):
        """Combina estadisticas del monitor y de los lectores RTSP."""
        ended_at = self.ended_at or datetime.now().astimezone()
        duration = self._duration()
        cameras = {}
        aggregate_timings = defaultdict(list)
        totals = defaultdict(int)

        for camera_id, row in self.rows.items():
            reader = readers[camera_id].performance_snapshot()
            received = int(reader["received_frames"])
            unique_analyzed = int(row["unique_analyzed_frames"])
            camera_timings = {}
            for key, values in row["timings"].items():
                camera_timings[key] = _timing_summary(values)
                aggregate_timings[key].extend(values)

            not_analyzed = max(0, received - unique_analyzed)
            cameras[camera_id] = {
                "stream": reader["stream"],
                "received_frames": received,
                "received_fps_run": round(received / duration, 3),
                "received_fps_active": reader["received_fps_active"],
                "analyzed_frames": row["analyzed_frames"],
                "unique_analyzed_frames": unique_analyzed,
                "analyzed_fps": round(row["analyzed_frames"] / duration, 3),
                "not_analyzed_frames_estimate": not_analyzed,
                "scheduler_skipped_frames": row["scheduler_skipped_frames"],
                "duplicate_analyses": row["duplicate_analyses"],
                "no_data_cycles": row["no_data_cycles"],
                "processing_errors": row["processing_errors"],
                "connection_attempts": reader["connection_attempts"],
                "successful_connections": reader["successful_connections"],
                "connection_errors": reader["connection_errors"],
                "reconnections": max(0, reader["successful_connections"] - 1),
                "timings_ms": camera_timings,
            }
            for key in (
                "received_frames",
                "analyzed_frames",
                "unique_analyzed_frames",
                "not_analyzed_frames_estimate",
                "scheduler_skipped_frames",
                "duplicate_analyses",
                "no_data_cycles",
                "processing_errors",
                "connection_errors",
            ):
                totals[key] += cameras[camera_id][key]

        aggregate = dict(totals)
        aggregate["received_fps"] = round(totals["received_frames"] / duration, 3)
        aggregate["analyzed_fps"] = round(totals["analyzed_frames"] / duration, 3)
        aggregate["timings_ms"] = {
            key: _timing_summary(values) for key, values in aggregate_timings.items()
        }
        return {
            "schema_version": 1,
            "started_at": self.started_at.isoformat(timespec="seconds"),
            "ended_at": ended_at.isoformat(timespec="seconds"),
            "duration_seconds": round(duration, 3),
            "configuration": configuration,
            "aggregate": aggregate,
            "cameras": cameras,
            "latency_scope": (
                "capture_to_result_ms begins when OpenCV returns a decoded frame; "
                "it excludes camera exposure, network transit and decoder time"
            ),
        }

    def write(self, path, readers, configuration):
        """Escribe atomica y legiblemente el resumen final de la ejecucion."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(
            json.dumps(self.summary(readers, configuration), indent=2),
            encoding="utf-8",
        )
        temporary.replace(target)
        return target
