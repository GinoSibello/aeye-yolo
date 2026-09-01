#!/usr/bin/env python3
"""Resume precision, conteo, velocidad y recursos de la matriz de Etapa 5."""

import argparse
import json
from pathlib import Path


TARGET_CAMERAS = 8
TARGET_FPS_PER_CAMERA = 6.0
TARGET_BUDGET_MS = 1000.0 / (TARGET_CAMERAS * TARGET_FPS_PER_CAMERA)


def rounded(value):
    """Redondea numeros sin convertir ausencia en cero."""
    return round(value, 4) if isinstance(value, (int, float)) else None


def load_run(directory):
    """Combina exactitud del validador con recursos de tegrastats."""
    accuracy = json.loads((directory / "accuracy.json").read_text())
    resources = json.loads((directory / "tegrastats_summary.json").read_text())
    name = accuracy["engine"].removesuffix(".engine")
    model, _, resolution = name.partition("_fp16_")
    speed = accuracy["speed_ms_per_image"]
    pipeline_ms = sum(
        speed.get(key, 0.0) for key in ("preprocess", "inference", "postprocess")
    )
    return {
        "engine": accuracy["engine"],
        "model": model,
        "family": "yolo26" if model.startswith("yolo26") else "yolo11",
        "scale": model[-1],
        "resolution": resolution,
        "engine_metadata": accuracy["engine_metadata"],
        "person_metrics": accuracy["person_metrics"],
        "operational_iou50": accuracy["operational_iou50"],
        "counting": accuracy["counting"],
        "speed_ms_per_image": speed,
        "pipeline_ms_per_image": rounded(pipeline_ms),
        "theoretical_fps": rounded(1000.0 / pipeline_ms),
        "target_budget_ms": rounded(TARGET_BUDGET_MS),
        "meets_8_camera_6fps_compute_budget": pipeline_ms <= TARGET_BUDGET_MS,
        "cpu_percent": resources["cpu_mean_across_active_cores_percent"],
        "gpu_percent": resources["gpu_percent"],
        "ram_used_mb": resources["ram_used_mb"],
        "power_vdd_in_mw": resources["power_vdd_in_mw"],
        "maximum_temperature_c": resources["maximum_temperature_c"],
    }


def dominates(left, right):
    """Indica si un candidato no pierde precision ni latencia frente a otro."""
    left_map = left["person_metrics"]["map50_95"]
    right_map = right["person_metrics"]["map50_95"]
    left_time = left["pipeline_ms_per_image"]
    right_time = right["pipeline_ms_per_image"]
    return (
        left_map >= right_map
        and left_time <= right_time
        and (left_map > right_map or left_time < right_time)
    )


def metric_delta(before, after):
    """Calcula cambio absoluto y relativo para un par comparable."""
    return {
        "before": rounded(before),
        "after": rounded(after),
        "delta": rounded(after - before),
        "relative_change_percent": rounded(
            100.0 * (after - before) / before if before else None
        ),
    }


def comparisons(runs):
    """Compara resolucion, escala y arquitectura manteniendo lo demas fijo."""
    rows = {}
    by_key = {(row["model"], row["resolution"]): row for row in runs}
    for model in sorted({row["model"] for row in runs}):
        low = by_key.get((model, "640x640"))
        high = by_key.get((model, "960x544"))
        if low and high:
            rows[f"{model}_960x544_minus_640x640"] = {
                "map50_95": metric_delta(
                    low["person_metrics"]["map50_95"],
                    high["person_metrics"]["map50_95"],
                ),
                "count_mae": metric_delta(
                    low["counting"]["mae_people_per_image"],
                    high["counting"]["mae_people_per_image"],
                ),
                "pipeline_ms": metric_delta(
                    low["pipeline_ms_per_image"],
                    high["pipeline_ms_per_image"],
                ),
            }
    return rows


def main():
    """Escribe una tabla completa y su frontera precision-latencia."""
    parser = argparse.ArgumentParser(description="Resumir Etapa 5")
    parser.add_argument("directory", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    runs = [
        load_run(path)
        for path in sorted(args.directory.iterdir())
        if path.is_dir() and (path / "accuracy.json").is_file()
    ]
    frontier = [
        row["engine"] for row in runs
        if not any(dominates(other, row) for other in runs if other is not row)
    ]
    ranked = sorted(
        runs,
        key=lambda row: (
            -row["person_metrics"]["map50_95"],
            row["pipeline_ms_per_image"],
        ),
    )
    payload = {
        "schema_version": 1,
        "target": {
            "cameras": TARGET_CAMERAS,
            "fps_per_camera": TARGET_FPS_PER_CAMERA,
            "sequential_compute_budget_ms": rounded(TARGET_BUDGET_MS),
        },
        "dataset_scope": (
            "COCO 2017 val is annotated real imagery, but it is not AEYE camera-domain data"
        ),
        "precision_policy": (
            "FP16 first; INT8 remains blocked until the selected model is validated "
            "against camera-domain annotations"
        ),
        "runs": ranked,
        "pareto_frontier_precision_latency": frontier,
        "resolution_comparisons": comparisons(runs),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
