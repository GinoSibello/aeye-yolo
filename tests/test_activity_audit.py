"""Pruebas de la auditoria local por turno y conteo visual."""

import importlib.util
import unittest
from datetime import date, datetime, timezone
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "tools" / "audit_activity_data.py"
)
SPEC = importlib.util.spec_from_file_location("activity_audit", MODULE_PATH)
activity_audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(activity_audit)


class ActivityAuditTest(unittest.TestCase):
    def test_visual_threshold_reports_error_and_bias(self):
        samples = [
            {"reported": 2, "manual": 2},
            {"reported": 2, "manual": 2},
            {"reported": 2, "manual": 2},
            {"reported": 2, "manual": 2},
            {"reported": 2, "manual": 2},
            {"reported": 2, "manual": 2},
            {"reported": 2, "manual": 2},
            {"reported": 2, "manual": 2},
            {"reported": 2, "manual": 2},
            {"reported": 3, "manual": 2},
        ]

        result = activity_audit.summarize_visual(samples, 10, 90.0)

        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["exact_percent"], 90.0)
        self.assertEqual(result["mae"], 0.1)
        self.assertEqual(result["signed_bias"], 0.1)
        self.assertEqual(result["overcounts"], 1)
        self.assertEqual(result["undercounts"], 0)

    def test_visual_sample_is_pending_until_minimum_is_reached(self):
        result = activity_audit.summarize_visual(
            [{"reported": 1, "manual": 1}], 10, 90.0
        )

        self.assertEqual(result["status"], "insufficient_samples")
        self.assertEqual(result["sample_count"], 1)

    def test_special_areas_are_audited_per_shift_without_staffing(self):
        class FakeAnalytics:
            @staticmethod
            def _samples(camera_id, start, end):
                return []

        setting = {
            "camera_id": "cam07",
            "timezone": "UTC",
            "max_sample_gap_seconds": 15,
            "shifts": [
                {
                    "id": "morning",
                    "name": "Turno mañana",
                    "start": "07:00",
                    "end": "16:00",
                },
                {
                    "id": "afternoon",
                    "name": "Turno tarde",
                    "start": "16:00",
                    "end": "00:00",
                },
            ],
        }

        rows = activity_audit._special_area_shifts(
            FakeAnalytics(),
            setting,
            date(2026, 9, 9),
            datetime(2026, 9, 9, 17, tzinfo=timezone.utc),
        )

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["period_status"], "complete")
        self.assertEqual(rows[1]["period_status"], "in_progress")
        self.assertIsNone(rows[0]["staffing_coverage_percent"])


if __name__ == "__main__":
    unittest.main()
