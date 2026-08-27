#!/usr/bin/env python3
"""Compara inferencia secuencial y batching sin incluir datos sensibles."""

import argparse
import json
from pathlib import Path


def rounded(value):
    """Redondea valores opcionales para mantener estable el resumen."""
    return round(value, 3) if isinstance(value, (int, float)) else None


def average(values):
    """Promedia una lista numerica o devuelve nulo si esta vacia."""
    return rounded(sum(values) / len(values)) if values else None


def load_run(directory):
    """Carga rendimiento y tegrastats de una corrida de Etapa 3."""
    performance = json.loads(
        (directory / "performance_summary.json").read_text(encoding="utf-8")
    )
    tegrastats = json.loads(
        (directory / "tegrastats_summary.json").read_text(encoding="utf-8")
    )
    configuration = performance["configuration"]
    cameras = list(performance["cameras"].values())
    active_fps = [
        row["analyzed_fps_active"]
        for row in cameras
        if row.get("analyzed_fps_active") is not None
    ]
    unique_fps = [
        row["unique_analyzed_fps_active"]
        for row in cameras
        if row.get("unique_analyzed_fps_active") is not None
    ]
    received_fps = [
        row["received_fps_active"]
        for row in cameras
        if row.get("received_fps_active") is not None
    ]
    aggregate = performance["aggregate"]
    batching = performance["batching"]
    return {
        "directory": str(directory),
        "mode": "batching" if configuration["batching_enabled"] else "sequential",
        "engine": configuration["engine"],
        "engine_batch_size": configuration["engine_batch_size"],
        "engine_dynamic": configuration["engine_dynamic"],
        "engine_precision": configuration["engine_precision"],
        "requested_max_batch_size": configuration["batching_max_batch_size"],
        "batch_timeout_ms": configuration["batching_timeout_ms"],
        "camera_count": len(cameras),
        "capture_backends": sorted({
            row["stream"].get("capture_backend") for row in cameras
        }),
        "requested_fps_per_camera": configuration[
            "requested_inference_fps_per_camera"
        ],
        "received_fps_per_camera_active_avg": average(received_fps),
        "analyzed_fps_per_camera_active_avg": average(active_fps),
        "unique_fps_per_camera_active_avg": average(unique_fps),
        "aggregate_analyzed_fps_full_window": aggregate["analyzed_fps"],
        "duplicate_analyses": aggregate["duplicate_analyses"],
        "no_data_cycles": aggregate["no_data_cycles"],
        "processing_errors": aggregate["processing_errors"],
        "connection_errors": aggregate["connection_errors"],
        "reconnections": sum(row["reconnections"] for row in cameras),
        "batching": batching,
        "timings_ms": aggregate["timings_ms"],
        "gpu_percent": tegrastats["gpu_percent"],
        "cpu_percent": tegrastats["cpu_mean_across_active_cores_percent"],
        "cpu_peak_core_percent": tegrastats["cpu_peak_core_percent"],
        "ram_used_mb": tegrastats["ram_used_mb"],
        "maximum_temperature_c": tegrastats["maximum_temperature_c"],
        "power_vdd_in_mw": tegrastats["power_vdd_in_mw"],
    }


def delta(before, after):
    """Devuelve diferencia absoluta y relativa de dos valores opcionales."""
    if not isinstance(before, (int, float)) or not isinstance(after, (int, float)):
        return {"sequential": before, "batching": after, "delta": None,
                "relative_change_percent": None}
    return {
        "sequential": before,
        "batching": after,
        "delta": rounded(after - before),
        "relative_change_percent": (
            rounded(100.0 * (after - before) / before) if before else None
        ),
    }


def comparison(runs):
    """Calcula deltas batching menos secuencial para capacidad y latencia."""
    by_mode = {row["mode"]: row for row in runs}
    if set(by_mode) != {"sequential", "batching"}:
        return None
    sequential = by_mode["sequential"]
    batching = by_mode["batching"]
    pairs = {
        "unique_fps_per_camera": (
            sequential["unique_fps_per_camera_active_avg"],
            batching["unique_fps_per_camera_active_avg"],
        ),
        "tensorrt_calls_per_second": (
            sequential["batching"]["calls_per_second"],
            batching["batching"]["calls_per_second"],
        ),
        "frames_per_tensorrt_call_avg": (
            sequential["batching"]["batch_size"]["avg"],
            batching["batching"]["batch_size"]["avg"],
        ),
        "detector_call_p95_ms": (
            sequential["batching"]["detector_call_ms"]["p95"],
            batching["batching"]["detector_call_ms"]["p95"],
        ),
        "per_image_inference_p95_ms": (
            sequential["timings_ms"]["inference_ms"]["p95"],
            batching["timings_ms"]["inference_ms"]["p95"],
        ),
        "schedule_lag_p95_ms": (
            sequential["timings_ms"]["schedule_lag_ms"]["p95"],
            batching["timings_ms"]["schedule_lag_ms"]["p95"],
        ),
        "capture_to_result_p95_ms": (
            sequential["timings_ms"]["capture_to_result_ms"]["p95"],
            batching["timings_ms"]["capture_to_result_ms"]["p95"],
        ),
        "cpu_avg_percent": (
            sequential["cpu_percent"]["avg"],
            batching["cpu_percent"]["avg"],
        ),
        "gpu_avg_percent": (
            sequential["gpu_percent"]["avg"],
            batching["gpu_percent"]["avg"],
        ),
        "ram_avg_mb": (
            sequential["ram_used_mb"]["avg"],
            batching["ram_used_mb"]["avg"],
        ),
        "power_avg_mw": (
            sequential["power_vdd_in_mw"]["avg"],
            batching["power_vdd_in_mw"]["avg"],
        ),
    }
    return {name: delta(*values) for name, values in pairs.items()}


def main():
    """Ordena las corridas y escribe la comparacion conjunta."""
    parser = argparse.ArgumentParser(description="Resume la etapa 3 de AEYE")
    parser.add_argument("directories", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    runs = sorted(
        (load_run(directory) for directory in args.directories),
        key=lambda row: row["mode"] != "sequential",
    )
    payload = {
        "schema_version": 1,
        "runs": runs,
        "comparison_batching_minus_sequential": comparison(runs),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
