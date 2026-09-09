import unittest
from datetime import datetime, timezone

from metrics.reporting_config import staffing_active
from metrics.staffing import CountSmoother, StaffingStateMachine


class StaffingTest(unittest.TestCase):
    def camera(self):
        return {
            "id": "cam01", "name": "Camara 01", "zone": "Caja",
            "monitor_staffing": True, "min_people": 1, "max_people": 2,
        }

    def config(self):
        return {
            "smoothing_window_seconds": 0,
            "incident_confirmation_seconds": 30,
            "recovery_confirmation_seconds": 15,
            "alert_after_seconds": 60,
        }

    def test_median_smoothing_ignores_short_zero(self):
        smoother = CountSmoother(window_seconds=10)
        self.assertEqual(smoother.add(1, at=0), 1)
        self.assertEqual(smoother.add(1, at=1), 1)
        self.assertEqual(smoother.add(0, at=2), 1)

    def test_hysteresis_confirms_opens_alerts_and_recovers(self):
        rule = StaffingStateMachine(self.camera(), self.config())
        self.assertEqual(rule.evaluate(0, at=0).rule_state, "confirming")
        opened = rule.evaluate(0, at=30)
        self.assertEqual(opened.transition["type"], "opened")
        self.assertEqual(opened.staffing_status, "missing")
        alerted = rule.evaluate(0, at=90)
        self.assertIsNotNone(alerted.alert)
        self.assertEqual(rule.evaluate(1, at=91).rule_state, "recovering")
        recovered = rule.evaluate(1, at=106)
        self.assertEqual(recovered.transition["type"], "closed")
        self.assertEqual(recovered.staffing_status, "ok")

    def test_no_data_breaks_continuity(self):
        rule = StaffingStateMachine(self.camera(), self.config())
        rule.evaluate(0, at=0)
        rule.evaluate(0, at=30)
        missing = rule.no_data()
        self.assertEqual(missing.data_status, "no_data")
        self.assertEqual(missing.transition["reason"], "no_data")
        self.assertEqual(rule.evaluate(0, at=31).rule_state, "confirming")

    def test_outside_schedule_closes_incident_and_suppresses_alert(self):
        rule = StaffingStateMachine(self.camera(), self.config())
        rule.evaluate(0, at=0)
        rule.evaluate(0, at=30)

        outside = rule.evaluate(0, at=90, monitoring=False)

        self.assertEqual(outside.rule_state, "outside_schedule")
        self.assertEqual(outside.transition["type"], "closed")
        self.assertIsNone(outside.alert)
        self.assertEqual(
            rule.evaluate(0, at=91, monitoring=True).rule_state,
            "confirming",
        )

    def test_staffing_schedule_includes_both_shifts_but_not_overnight(self):
        settings = {
            "role": "workstation",
            "timezone": "UTC",
            "workdays": [0],
            "shifts": [
                {"start": "07:00", "end": "16:00"},
                {"start": "16:00", "end": "00:00"},
            ],
        }

        self.assertTrue(staffing_active(
            settings, datetime(2026, 8, 10, 7, tzinfo=timezone.utc)
        ))
        self.assertTrue(staffing_active(
            settings, datetime(2026, 8, 10, 16, tzinfo=timezone.utc)
        ))
        self.assertFalse(staffing_active(
            settings, datetime(2026, 8, 11, 1, tzinfo=timezone.utc)
        ))
        self.assertFalse(staffing_active(
            settings, datetime(2026, 8, 15, 12, tzinfo=timezone.utc)
        ))


if __name__ == "__main__":
    unittest.main()
