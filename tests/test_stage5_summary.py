"""Pruebas de la comparacion reproducible de modelos de Etapa 5."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "tools" / "summarize_stage5.py"
SPEC = importlib.util.spec_from_file_location("summarize_stage5", MODULE_PATH)
stage5 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(stage5)


def candidate(model, resolution, map50_95, pipeline_ms, count_mae=1.0):
    """Construye la parte minima usada por comparaciones y Pareto."""
    return {
        "engine": f"{model}_fp16_{resolution}.engine",
        "model": model,
        "resolution": resolution,
        "person_metrics": {"map50_95": map50_95},
        "pipeline_ms_per_image": pipeline_ms,
        "counting": {"mae_people_per_image": count_mae},
    }


class Stage5SummaryTests(unittest.TestCase):
    def test_dominates_requires_no_precision_or_latency_regression(self):
        fast_accurate = candidate("yolo26s", "640x640", 0.59, 16.0)
        slow_less_accurate = candidate("yolo11s", "960x544", 0.58, 20.0)
        faster_less_accurate = candidate("yolo26n", "640x640", 0.51, 10.0)

        self.assertTrue(stage5.dominates(fast_accurate, slow_less_accurate))
        self.assertFalse(stage5.dominates(fast_accurate, faster_less_accurate))
        self.assertFalse(stage5.dominates(fast_accurate, fast_accurate))

    def test_resolution_comparison_reports_accuracy_count_and_cost(self):
        runs = [
            candidate("yolo26s", "640x640", 0.59, 16.0, 0.90),
            candidate("yolo26s", "960x544", 0.60, 21.0, 1.00),
        ]

        result = stage5.comparisons(runs)["yolo26s_960x544_minus_640x640"]

        self.assertEqual(result["map50_95"]["delta"], 0.01)
        self.assertEqual(result["count_mae"]["delta"], 0.1)
        self.assertEqual(result["pipeline_ms"]["delta"], 5.0)

    def test_load_run_combines_accuracy_resources_and_budget(self):
        accuracy = {
            "engine": "yolo26s_fp16_640x640.engine",
            "engine_metadata": {
                "imgsz": [640, 640],
                "batch": 1,
                "dynamic": False,
                "precision": "fp16",
                "end2end": True,
            },
            "person_metrics": {"map50_95": 0.59},
            "operational_iou50": {"precision": 0.62, "recall": 0.82},
            "counting": {"mae_people_per_image": 0.91},
            "speed_ms_per_image": {
                "preprocess": 3.0,
                "inference": 11.5,
                "postprocess": 1.7,
            },
        }
        resources = {
            "cpu_mean_across_active_cores_percent": {"avg": 16.0},
            "gpu_percent": {"avg": 42.0},
            "ram_used_mb": {"avg": 3900.0},
            "power_vdd_in_mw": {"avg": 7700.0},
            "maximum_temperature_c": 55.0,
        }
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "accuracy.json").write_text(json.dumps(accuracy))
            (directory / "tegrastats_summary.json").write_text(
                json.dumps(resources)
            )

            result = stage5.load_run(directory)

        self.assertEqual(result["model"], "yolo26s")
        self.assertEqual(result["resolution"], "640x640")
        self.assertEqual(result["pipeline_ms_per_image"], 16.2)
        self.assertTrue(result["meets_8_camera_6fps_compute_budget"])


if __name__ == "__main__":
    unittest.main()
