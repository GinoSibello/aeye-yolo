#!/usr/bin/env python3
"""Compara captura FFmpeg y GStreamer NVDEC sin incluir datos sensibles."""

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
    """Carga rendimiento y tegrastats de una corrida de captura."""
    performance = json.loads(
        (directory / "performance_summary.json").read_text(encoding="utf-8")
    )
    tegrastats = json.loads(
        (directory / "tegrastats_summary.json").read_text(encoding="utf-8")
    )
    cameras = list(performance["cameras"].values())
    active_fps = [
        row["analyzed_fps_active"]
        for row in cameras
        if row.get("analyzed_fps_active") is not None
    ]
    unique_fps = [
        row.get("unique_analyzed_fps_active")
        or (
            (row["unique_analyzed_frames"] - 1)
            / row["active_analysis_seconds"]
        )
        for row in cameras
        if row.get("active_analysis_seconds", 0) > 0
        and row["unique_analyzed_frames"] > 1
    ]
    received_fps = [
        row["received_fps_active"]
        for row in cameras
        if row.get("received_fps_active") is not None
    ]
    actual_backends = sorted(
        {
            row["stream"].get("capture_backend")
            for row in cameras
            if row["stream"].get("capture_backend")
        }
    )
    fallback_cameras = sum(
        bool(row["stream"].get("fallback_reason"))
        or row["stream"].get("capture_backend")
        != performance["configuration"]["requested_capture_backend"]
        for row in cameras
    )
    aggregate = performance["aggregate"]

    return {
        "directory": str(directory),
        "requested_capture_backend": performance["configuration"][
            "requested_capture_backend"
        ],
        "actual_capture_backends": actual_backends,
        "hardware_decode_all_cameras": all(
            row["stream"].get("hardware_decode") is True for row in cameras
        ),
        "fallback_cameras": fallback_cameras,
        "camera_count": len(cameras),
        "requested_fps_per_camera": performance["configuration"][
            "requested_inference_fps_per_camera"
        ],
        "received_fps_per_camera_active_avg": average(received_fps),
        "analyzed_fps_per_camera_active_avg": average(active_fps),
        "unique_fps_per_camera_active_avg": average(unique_fps),
        "aggregate_received_fps_full_window": aggregate["received_fps"],
        "aggregate_analyzed_fps_full_window": aggregate["analyzed_fps"],
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
        "largest_free_block": tegrastats["largest_free_block"],
        "maximum_temperature_c": tegrastats["maximum_temperature_c"],
        "power_vdd_in_mw": tegrastats["power_vdd_in_mw"],
        "nvdec_percent": tegrastats["nvdec_percent"],
    }


def comparison(runs):
    """Calcula deltas NVDEC menos FFmpeg para las metricas principales."""
    by_backend = {row["requested_capture_backend"]: row for row in runs}
    if set(by_backend) != {"ffmpeg", "gstreamer_nvdec"}:
        return None
    ffmpeg = by_backend["ffmpeg"]
    nvdec = by_backend["gstreamer_nvdec"]
    values = {
        "cpu_avg_percent": (
            ffmpeg["cpu_percent"]["avg"],
            nvdec["cpu_percent"]["avg"],
        ),
        "cpu_peak_core_p95_percent": (
            ffmpeg["cpu_peak_core_percent"]["p95"],
            nvdec["cpu_peak_core_percent"]["p95"],
        ),
        "gpu_avg_percent": (
            ffmpeg["gpu_percent"]["avg"],
            nvdec["gpu_percent"]["avg"],
        ),
        "frame_age_p95_ms": (
            ffmpeg["timings_ms"]["frame_age_ms"]["p95"],
            nvdec["timings_ms"]["frame_age_ms"]["p95"],
        ),
        "capture_to_result_p95_ms": (
            ffmpeg["timings_ms"]["capture_to_result_ms"]["p95"],
            nvdec["timings_ms"]["capture_to_result_ms"]["p95"],
        ),
        "power_avg_mw": (
            ffmpeg["power_vdd_in_mw"]["avg"],
            nvdec["power_vdd_in_mw"]["avg"],
        ),
    }
    result = {}
    for name, (before, after) in values.items():
        result[name] = {
            "ffmpeg": before,
            "gstreamer_nvdec": after,
            "delta": rounded(after - before),
            "relative_change_percent": (
                rounded(100.0 * (after - before) / before) if before else None
            ),
        }
    return result


def main():
    """Ordena las corridas y escribe una comparacion conjunta."""
    parser = argparse.ArgumentParser(description="Resume la etapa 2 de AEYE")
    parser.add_argument("directories", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    runs = sorted(
        (load_run(directory) for directory in args.directories),
        key=lambda row: row["requested_capture_backend"],
    )
    payload = {
        "schema_version": 1,
        "runs": runs,
        "comparison_nvdec_minus_ffmpeg": comparison(runs),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
