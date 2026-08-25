#!/usr/bin/env python3
"""Compara las corridas de FPS de la etapa 1 sin incluir datos sensibles."""

import argparse
import json
from pathlib import Path


def rounded(value):
    """Redondea valores opcionales para una tabla legible."""
    return round(value, 3) if isinstance(value, (int, float)) else None


def load_run(directory):
    """Carga los dos resumenes producidos por un baseline."""
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
    unique_active_fps = [
        (row["unique_analyzed_frames"] - 1) / row["active_analysis_seconds"]
        for row in cameras
        if row.get("active_analysis_seconds", 0) > 0
        and row["unique_analyzed_frames"] > 1
    ]
    aggregate = performance["aggregate"]
    received = aggregate["received_frames"]
    not_analyzed = aggregate["not_analyzed_frames_estimate"]
    requested = performance["configuration"][
        "requested_inference_fps_per_camera"
    ]

    return {
        "directory": str(directory),
        "requested_fps_per_camera": requested,
        "active_fps_per_camera_min": rounded(min(active_fps)) if active_fps else None,
        "active_fps_per_camera_avg": (
            rounded(sum(active_fps) / len(active_fps)) if active_fps else None
        ),
        "active_fps_per_camera_max": rounded(max(active_fps)) if active_fps else None,
        "target_attainment_percent": (
            rounded(100.0 * (sum(active_fps) / len(active_fps)) / requested)
            if active_fps and requested
            else None
        ),
        "unique_active_fps_per_camera_min": (
            rounded(min(unique_active_fps)) if unique_active_fps else None
        ),
        "unique_active_fps_per_camera_avg": (
            rounded(sum(unique_active_fps) / len(unique_active_fps))
            if unique_active_fps
            else None
        ),
        "unique_active_fps_per_camera_max": (
            rounded(max(unique_active_fps)) if unique_active_fps else None
        ),
        "unique_target_attainment_percent": (
            rounded(
                100.0 * sum(unique_active_fps) / len(unique_active_fps) / requested
            )
            if unique_active_fps and requested
            else None
        ),
        "aggregate_analyzed_fps_full_window": aggregate["analyzed_fps"],
        "aggregate_received_fps_full_window": aggregate["received_fps"],
        "not_analyzed_percent": (
            rounded(100.0 * not_analyzed / received) if received else None
        ),
        "duplicate_analyses": aggregate["duplicate_analyses"],
        "unique_analyses_percent": (
            rounded(
                100.0
                * aggregate["unique_analyzed_frames"]
                / aggregate["analyzed_frames"]
            )
            if aggregate["analyzed_frames"]
            else None
        ),
        "no_data_cycles": aggregate["no_data_cycles"],
        "processing_errors": aggregate["processing_errors"],
        "connection_errors": aggregate["connection_errors"],
        "timings_ms": aggregate["timings_ms"],
        "gpu_percent": tegrastats["gpu_percent"],
        "cpu_percent": tegrastats["cpu_mean_across_active_cores_percent"],
        "cpu_peak_core_percent": tegrastats["cpu_peak_core_percent"],
        "ram_used_mb": tegrastats["ram_used_mb"],
        "maximum_temperature_c": tegrastats["maximum_temperature_c"],
        "power_vdd_in_mw": tegrastats["power_vdd_in_mw"],
        "nvdec_percent": tegrastats["nvdec_percent"],
    }


def main():
    """Ordena las corridas por FPS solicitado y escribe el resumen conjunto."""
    parser = argparse.ArgumentParser(description="Resume la etapa 1 de AEYE")
    parser.add_argument("directories", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    runs = sorted(
        (load_run(directory) for directory in args.directories),
        key=lambda row: row["requested_fps_per_camera"],
    )
    payload = {"schema_version": 1, "runs": runs}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
