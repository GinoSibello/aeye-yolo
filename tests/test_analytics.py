import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from database.repository import Repository
from metrics.analytics import Analytics
from metrics.recorder import MetricsRecorder


class AnalyticsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Repository(Path(self.tmp.name) / "test.db")
        self.analytics = Analytics(self.repo)
        self.start = datetime(2026, 8, 10, 8, tzinfo=timezone.utc)

    def tearDown(self):
        self.tmp.cleanup()

    def test_staffing_minutes_hourly_occupancy_and_incidents(self):
        camera = {"id":"cam01","zone":"Caja","min_people":2,"max_people":3}
        recorder = MetricsRecorder(self.repo, sample_every_seconds=0)
        recorder.observe_staffing(camera, 1, self.start)
        recorder.observe_staffing(camera, 1, self.start + timedelta(minutes=25))
        recorder.observe_staffing(camera, 2, self.start + timedelta(minutes=30))

        end = self.start + timedelta(hours=1)
        self.assertAlmostEqual(self.analytics.minutes_below_minimum("Caja", self.start, end)["minutes"], 30, places=1)
        self.assertEqual(self.analytics.long_incidents(self.start, end, 20)["incidents"], 1)
        hourly = self.analytics.average_occupancy_by_hour(self.start, end, "Caja")[0]
        self.assertEqual(hourly["avg_occupancy"], 1.33)

    def test_false_positive_ranking_requires_reviews(self):
        for camera, values in {"cam01":[1,1,0], "cam02":[1,0,0,0]}.items():
            for value in values:
                self.repo.execute("INSERT INTO detection_reviews(camera_id,detection_at,is_false_positive) VALUES(?,?,?)",
                                  (camera, self.start.isoformat(), value))
        rows = self.analytics.false_positives_by_camera(self.start, self.start + timedelta(days=1))
        self.assertEqual(rows[0]["camera_id"], "cam01")


if __name__ == "__main__":
    unittest.main()
