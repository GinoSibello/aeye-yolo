#!/usr/bin/env python3
"""Compara rutas de copias y conversiones de la Etapa 4."""

import argparse
import json
from pathlib import Path


def rounded(value):
    """Redondea valores opcionales para mantener estable el resumen."""
    return round(value, 3) if isinstance(value, (int, float)) else None


def average(values):
    """Promedia una lista numerica o devuelve nulo si esta vacia."""
    return rounded(sum(values) / len(values)) if values else None


def run_mode(configuration):
    """Nombra una combinacion de rutas sin depender del nombre del directorio."""
    settings = {
        (True, "split"): "baseline",
        (False, "split"): "shared_frame",
        (True, "packed"): "packed_results",
        (False, "packed"): "optimized",
    }
    return settings[(
        configuration["copy_latest_frame"],
        configuration["result_transfer"],
    )]


def load_run(directory):
    """Carga rendimiento y tegrastats sin incorporar datos sensibles."""
    performance = json.loads(
        (directory / "performance_summary.json").read_text(encoding="utf-8")
    )
    tegrastats = json.loads(
        (directory / "tegrastats_summary.json").read_text(encoding="utf-8")
    )
    configuration = performance["configuration"]
    cameras = list(performance["cameras"].values())
    aggregate = performance["aggregate"]
    duration = performance["duration_seconds"]
    active_fps = [
        row["analyzed_fps_active"] for row in cameras
        if row.get("analyzed_fps_active") is not None
    ]
    unique_fps = [
        row["unique_analyzed_fps_active"] for row in cameras
        if row.get("unique_analyzed_fps_active") is not None
    ]
    snapshot_traffic = 0.0
    if configuration["copy_latest_frame"]:
        for row in cameras:
            stream = row["stream"]
            width = stream.get("width")
            height = stream.get("height")
            if width and height:
                snapshot_traffic += (
                    width * height * 3 * row["analyzed_frames"] / duration
                )
    return {
        "directory": str(directory),
        "mode": run_mode(configuration),
        "copy_latest_frame": configuration["copy_latest_frame"],
        "result_transfer": configuration["result_transfer"],
        "camera_count": len(cameras),
        "capture_backends": sorted({
            row["stream"].get("capture_backend") for row in cameras
        }),
        "requested_fps_per_camera": configuration[
            "requested_inference_fps_per_camera"
        ],
        "analyzed_fps_per_camera_active_avg": average(active_fps),
        "unique_fps_per_camera_active_avg": average(unique_fps),
        "aggregate_analyzed_fps_full_window": aggregate["analyzed_fps"],
        "snapshot_copy_traffic_mib_per_second": rounded(
            snapshot_traffic / (1024 * 1024)
        ),
        "duplicate_analyses": aggregate["duplicate_analyses"],
        "no_data_cycles": aggregate["no_data_cycles"],
        "processing_errors": aggregate["processing_errors"],
        "connection_errors": aggregate["connection_errors"],
        "reconnections": sum(row["reconnections"] for row in cameras),
        "timings_ms": aggregate["timings_ms"],
        "gpu_percent": tegrastats["gpu_percent"],
        "cpu_percent": tegrastats["cpu_mean_across_active_cores_percent"],
        "cpu_peak_core_percent": tegrastats["cpu_peak_core_percent"],
        "ram_used_mb": tegrastats["ram_used_mb"],
        "maximum_temperature_c": tegrastats["maximum_temperature_c"],
        "power_vdd_in_mw": tegrastats["power_vdd_in_mw"],
    }


def delta(baseline, candidate):
    """Devuelve diferencia absoluta y relativa respecto del brazo historico."""
    if (
        not isinstance(baseline, (int, float))
        or not isinstance(candidate, (int, float))
    ):
        return {
            "baseline": baseline,
            "candidate": candidate,
            "delta": None,
            "relative_change_percent": None,
        }
    return {
        "baseline": baseline,
        "candidate": candidate,
        "delta": rounded(candidate - baseline),
        "relative_change_percent": (
            rounded(100.0 * (candidate - baseline) / baseline)
            if baseline else None
        ),
    }


def comparison(baseline, candidate):
    """Selecciona capacidad, latencia y recursos relevantes para la decision."""
    pairs = {
        "unique_fps_per_camera": (
            baseline["unique_fps_per_camera_active_avg"],
            candidate["unique_fps_per_camera_active_avg"],
        ),
        "frame_snapshot_avg_ms": (
            baseline["timings_ms"]["frame_snapshot_ms"]["avg"],
            candidate["timings_ms"]["frame_snapshot_ms"]["avg"],
        ),
        "result_conversion_avg_ms": (
            baseline["timings_ms"]["result_conversion_ms"]["avg"],
            candidate["timings_ms"]["result_conversion_ms"]["avg"],
        ),
        "preprocess_avg_ms": (
            baseline["timings_ms"]["preprocess_ms"]["avg"],
            candidate["timings_ms"]["preprocess_ms"]["avg"],
        ),
        "postprocess_avg_ms": (
            baseline["timings_ms"]["postprocess_ms"]["avg"],
            candidate["timings_ms"]["postprocess_ms"]["avg"],
        ),
        "detector_total_p95_ms": (
            baseline["timings_ms"]["detector_total_ms"]["p95"],
            candidate["timings_ms"]["detector_total_ms"]["p95"],
        ),
        "capture_to_result_p95_ms": (
            baseline["timings_ms"]["capture_to_result_ms"]["p95"],
            candidate["timings_ms"]["capture_to_result_ms"]["p95"],
        ),
        "cpu_avg_percent": (
            baseline["cpu_percent"]["avg"], candidate["cpu_percent"]["avg"]
        ),
        "gpu_avg_percent": (
            baseline["gpu_percent"]["avg"], candidate["gpu_percent"]["avg"]
        ),
        "ram_avg_mb": (
            baseline["ram_used_mb"]["avg"], candidate["ram_used_mb"]["avg"]
        ),
        "power_avg_mw": (
            baseline["power_vdd_in_mw"]["avg"],
            candidate["power_vdd_in_mw"]["avg"],
        ),
    }
    return {name: delta(*values) for name, values in pairs.items()}


def main():
    """Ordena las corridas y escribe comparaciones contra el baseline."""
    parser = argparse.ArgumentParser(description="Resume la etapa 4 de AEYE")
    parser.add_argument("directories", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    order = {"baseline": 0, "shared_frame": 1, "packed_results": 2, "optimized": 3}
    runs = sorted(
        (load_run(directory) for directory in args.directories),
        key=lambda row: order[row["mode"]],
    )
    by_mode = {row["mode"]: row for row in runs}
    if set(by_mode) != set(order):
        raise ValueError("Se requieren los cuatro modos de Etapa 4")
    baseline = by_mode["baseline"]
    payload = {
        "schema_version": 1,
        "runs": runs,
        "comparisons_minus_baseline": {
            mode: comparison(baseline, by_mode[mode])
            for mode in ("shared_frame", "packed_results", "optimized")
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
