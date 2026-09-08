"""Pruebas del reporte anonimo por horarios y puestos."""

import json
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from database.repository import Repository
from metrics.activity import ActivityAnalytics
from metrics.weekly import WeeklyActivityAnalytics
from metrics.reporting_config import (
    camera_reporting,
    normalize_reporting,
    sync_reporting_configuration,
)


class ActivityReportingTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.repository = Repository(Path(self.temporary.name) / "activity.db")
        self.config = {
            "reporting": {
                "timezone": "UTC",
                "workdays": [0],
                "shift": {
                    "start": "08:00",
                    "end": "17:00",
                    "arrival_grace_minutes": 5,
                    "early_departure_tolerance_minutes": 5,
                    "overtime_tolerance_minutes": 10,
                    "overtime_observation_minutes": 60,
                },
                "meal": {
                    "window_start": "12:00",
                    "window_end": "13:00",
                    "allowed_minutes": 30,
                },
                "max_sample_gap_seconds": 90,
                "absence_merge_gap_minutes": 2,
            },
            "cameras": [{
                "id": "cam01",
                "name": "Puesto corte",
                "zone": "Corte",
                "enabled": True,
                "role": "workstation",
                "reporting_enabled": True,
                "expected_people": 2,
                "monitor_staffing": True,
            }],
        }
        sync_reporting_configuration(
            self.repository,
            self.config,
            datetime(2026, 8, 10, tzinfo=timezone.utc),
        )
        self.analytics = ActivityAnalytics(self.repository)

    def tearDown(self):
        self.repository.close()
        self.temporary.cleanup()

    def record_day(self):
        """Genera un turno completo con cuatro eventos conocidos."""
        current = datetime(2026, 8, 10, 8, tzinfo=timezone.utc)
        end = datetime(2026, 8, 10, 18, tzinfo=timezone.utc)
        while current <= end:
            if current < datetime(2026, 8, 10, 8, 10, tzinfo=timezone.utc):
                count = 1
            elif current < datetime(2026, 8, 10, 12, tzinfo=timezone.utc):
                count = 2
            elif current < datetime(2026, 8, 10, 12, 45, tzinfo=timezone.utc):
                count = 1
            elif current < datetime(2026, 8, 10, 16, 40, tzinfo=timezone.utc):
                count = 2
            elif current < datetime(2026, 8, 10, 17, 30, tzinfo=timezone.utc):
                count = 1
            else:
                count = 0
            self.repository.add_occupancy(
                "cam01", "Corte", current, count, count,
                2, 2, "valid", "ok" if count == 2 else "missing",
            )
            current += timedelta(minutes=1)

    def test_daily_report_estimates_schedule_events_without_identity(self):
        self.record_day()

        report = self.analytics.daily_report(date(2026, 8, 10))
        row = report["workstations"][0]

        self.assertEqual(row["arrival"]["late_arrivals_estimated"], 1)
        self.assertEqual(row["arrival"]["average_late_minutes"], 10)
        self.assertEqual(row["meal"]["breaks_estimated"], 1)
        self.assertEqual(row["meal"]["overruns_estimated"], 1)
        self.assertEqual(row["meal"]["average_break_minutes"], 45)
        self.assertEqual(
            row["departure"]["early_departures_estimated"], 1
        )
        self.assertEqual(row["departure"]["average_early_minutes"], 20)
        self.assertEqual(
            row["departure"]["overtime_departures_estimated"], 1
        )
        self.assertGreaterEqual(
            row["departure"]["average_overtime_minutes"], 29
        )
        self.assertEqual(report["summary"]["late_arrivals_estimated"], 1)

    def test_weekly_report_uses_monday_and_preserves_measurement_days(self):
        self.record_day()

        report = WeeklyActivityAnalytics(
            self.repository
        ).weekly_report(date(2026, 8, 12))
        row = report["workstations"][0]

        self.assertEqual(report["week_start"], "2026-08-10")
        self.assertEqual(report["week_end"], "2026-08-16")
        self.assertEqual(row["scheduled_days"], 1)
        self.assertEqual(row["measured_days"], 1)
        self.assertGreater(row["occupancy_percent"], 80)
        self.assertLess(row["occupancy_percent"], 100)
        self.assertEqual(row["arrival"]["late_arrivals_estimated"], 1)
        self.assertEqual(row["meal"]["overruns_estimated"], 1)
        self.assertEqual(
            report["limitations"]["restroom_by_workstation"],
            "not_attributable",
        )

    def test_daily_report_counts_only_emitted_alerts(self):
        self.record_day()
        incident = self.repository.start_incident(
            "cam01", "Corte", "missing",
            datetime(2026, 8, 10, 9, tzinfo=timezone.utc),
            2, 2, 1,
        )
        self.repository.alert_incident(
            incident, datetime(2026, 8, 10, 9, 15, tzinfo=timezone.utc)
        )
        self.repository.start_incident(
            "cam01", "Corte", "extra",
            datetime(2026, 8, 10, 10, tzinfo=timezone.utc),
            2, 2, 3,
        )

        report = self.analytics.daily_report("2026-08-10")

        self.assertEqual(report["summary"]["alerts_total"], 1)
        self.assertEqual(report["summary"]["missing_alerts"], 1)
        self.assertEqual(report["summary"]["extra_alerts"], 0)
        self.assertEqual(report["workstations"][0]["alerts"]["total"], 1)

    def test_monthly_report_uses_calendar_boundaries_and_daily_evidence(self):
        self.record_day()
        incident = self.repository.start_incident(
            "cam01", "Corte", "missing",
            datetime(2026, 8, 10, 9, tzinfo=timezone.utc),
            2, 2, 1,
        )
        self.repository.alert_incident(
            incident, datetime(2026, 8, 10, 9, 15, tzinfo=timezone.utc)
        )

        report = WeeklyActivityAnalytics(
            self.repository
        ).monthly_report(date(2026, 8, 20))
        row = report["workstations"][0]

        self.assertEqual(report["period"], "monthly")
        self.assertEqual(report["month_start"], "2026-08-01")
        self.assertEqual(report["month_end"], "2026-08-31")
        self.assertEqual(len(report["daily"]), 31)
        self.assertEqual(len(row["daily"]), 31)
        self.assertEqual(len(row["hourly"]), 24)
        self.assertEqual(row["hourly"][8]["hour"], "08:00")
        self.assertEqual(row["arrival"]["late_arrivals_estimated"], 1)
        self.assertEqual(row["alerts"]["total"], 1)
        self.assertEqual(row["daily"][9]["alerts_total"], 1)
        self.assertEqual(report["summary"]["alerts_total"], 1)

    def test_no_data_reduces_coverage_instead_of_occupancy(self):
        start = datetime(2026, 8, 10, 8, tzinfo=timezone.utc)
        for minute in range(15):
            status = "no_data" if minute < 10 else "valid"
            count = None if status == "no_data" else 2
            self.repository.add_occupancy(
                "cam01", "Corte", start + timedelta(minutes=minute),
                count, count, 2, 2, status,
                "unknown" if status == "no_data" else "ok",
            )

        row = self.analytics.daily_report("2026-08-10")["workstations"][0]

        self.assertEqual(row["arrival"]["status"], "insufficient_data")
        self.assertLess(row["data_coverage_percent"], 2)

    def test_incomplete_configuration_is_exposed_not_invented(self):
        config = json.loads(json.dumps(self.config))
        config["cameras"][0].pop("expected_people")
        config["cameras"][0]["min_people"] = 0
        config["cameras"][0]["max_people"] = 99
        config["reporting"]["shift"] = {}
        sync_reporting_configuration(self.repository, config)

        report = self.analytics.daily_report("2026-08-10")
        row = report["workstations"][0]

        self.assertEqual(row["configuration_status"], "pending")
        self.assertIsNone(row["expected_people"])
        self.assertEqual(row["arrival"]["status"], "not_configured")
        self.assertIsNone(report["summary"]["expected_people"])
        self.assertIsNone(report["summary"]["late_arrivals_estimated"])
        self.assertIsNone(report["summary"]["person_hours"])

    def test_camera_can_override_meal_duration(self):
        camera = dict(self.config["cameras"][0])
        camera["reporting"] = {
            "meal": {"allowed_minutes": 45},
        }

        settings = camera_reporting(
            camera, normalize_reporting(self.config)
        )

        self.assertEqual(settings["meal_allowed_minutes"], 45)


if __name__ == "__main__":
    unittest.main()
