import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from database.repository import Repository
from metrics.analytics import Analytics
from metrics.recorder import MetricsRecorder
from metrics.staffing import StaffingObservation


class AnalyticsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Repository(Path(self.tmp.name) / "test.db")
        self.analytics = Analytics(self.repo)
        self.start = datetime(2026, 8, 10, 8, tzinfo=timezone.utc)

    def tearDown(self):
        self.repo.close()
        self.tmp.cleanup()

    @staticmethod
    def observation(raw, smoothed, status, transition=None):
        return StaffingObservation(
            "valid", raw, smoothed, status, status, transition=transition
        )

    def test_staffing_minutes_hourly_occupancy_and_incidents(self):
        camera = {"id":"cam01","zone":"Caja","min_people":2,"max_people":3}
        recorder = MetricsRecorder(self.repo, sample_every_seconds=0)
        recorder.observe(camera, self.observation(1, 1, "missing", {"type":"opened","kind":"missing"}), self.start)
        recorder.observe(camera, self.observation(1, 1, "missing"), self.start + timedelta(minutes=25))
        recorder.observe(camera, self.observation(2, 2, "ok", {"type":"closed","reason":"recovered"}), self.start + timedelta(minutes=30))

        end = self.start + timedelta(hours=1)
        self.assertAlmostEqual(self.analytics.minutes_below_minimum("Caja", self.start, end)["minutes"], 30, places=1)
        self.assertEqual(self.analytics.long_incidents(self.start, end, 20)["incidents"], 1)
        hourly = self.analytics.average_occupancy_by_hour(self.start, end, "Caja")[0]
        self.assertEqual(hourly["avg_occupancy"], 1.33)

    def test_no_data_is_not_counted_as_zero_or_missing_time(self):
        camera = {"id":"cam01","zone":"Caja","min_people":1,"max_people":2}
        recorder = MetricsRecorder(self.repo, sample_every_seconds=0)
        recorder.observe(camera, self.observation(0, 0, "missing", {"type":"opened","kind":"missing"}), self.start)
        recorder.observe(
            camera,
            StaffingObservation("no_data", None, None, "unknown", "no_data", {"type":"closed","reason":"no_data"}),
            self.start + timedelta(minutes=5),
        )
        recorder.observe(camera, self.observation(1, 1, "ok"), self.start + timedelta(minutes=20))

        result = self.analytics.minutes_below_minimum(
            "Caja", self.start, self.start + timedelta(minutes=30)
        )
        self.assertEqual(result["minutes"], 0)
        samples = self.repo.query(
            "SELECT people_count,data_status,status FROM occupancy_samples ORDER BY sampled_at"
        )
        self.assertIsNone(samples[1]["people_count"])
        self.assertEqual(samples[1]["data_status"], "no_data")

    def test_restart_closes_incident_at_last_valid_sample(self):
        camera = {"id":"cam01","zone":"Caja","min_people":1,"max_people":2}
        recorder = MetricsRecorder(self.repo, sample_every_seconds=0)
        recorder.observe(camera, self.observation(0, 0, "missing", {"type":"opened","kind":"missing"}), self.start)
        recorder.observe(camera, self.observation(0, 0, "missing"), self.start + timedelta(minutes=5))

        restarted = MetricsRecorder(self.repo, sample_every_seconds=0)
        self.assertEqual(restarted.recover_after_restart(), 1)
        incident = self.repo.query("SELECT * FROM incidents")[0]
        self.assertEqual(incident["closure_reason"], "process_restart")
        self.assertAlmostEqual(incident["duration_seconds"], 300, places=1)

    def test_migrations_can_run_again_without_changing_the_schema(self):
        path = self.repo.path
        self.repo.close()
        reopened = Repository(path)
        migrations = reopened.query(
            "SELECT name FROM schema_migrations ORDER BY name"
        )
        self.assertEqual(
            [row["name"] for row in migrations],
            ["001_initial.sql", "002_data_quality.sql"],
        )
        reopened.close()

    def test_false_positive_ranking_requires_reviews(self):
        for camera, values in {"cam01":[1,1,0], "cam02":[1,0,0,0]}.items():
            for value in values:
                self.repo.execute("INSERT INTO detection_reviews(camera_id,detection_at,is_false_positive) VALUES(?,?,?)",
                                  (camera, self.start.isoformat(), value))
        rows = self.analytics.false_positives_by_camera(self.start, self.start + timedelta(days=1))
        self.assertEqual(rows[0]["camera_id"], "cam01")


if __name__ == "__main__":
    unittest.main()
