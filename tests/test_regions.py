"""Pruebas de ROI y cruces anonimos de lineas."""

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from database.repository import Repository
from metrics.access import AccessRecorder
from vision.regions import AccessEvent, AccessLineTracker, tracks_in_roi


def track(track_id, bottom_y, left=40, right=60):
    return SimpleNamespace(
        track_id=track_id,
        box=[left, bottom_y - 20, right, bottom_y],
    )


class RegionTest(unittest.TestCase):
    def test_roi_uses_bottom_center_of_track(self):
        roi = [[0, 0], [0.5, 0], [0.5, 1], [0, 1]]
        tracks = [track(1, 50, 10, 30), track(2, 50, 70, 90)]

        selected = tracks_in_roi(tracks, (100, 100, 3), roi)

        self.assertEqual([item.track_id for item in selected], [1])

    def test_access_line_emits_entry_and_exit_on_stable_crossing(self):
        line = AccessLineTracker({
            "enabled": True,
            "start": [0, 0.5],
            "end": [1, 0.5],
            "inside_side": "left",
            "hysteresis": 0.01,
        })

        self.assertEqual(line.update([track(1, 40)], (100, 100, 3), 1), [])
        entered = line.update([track(1, 60)], (100, 100, 3), 2)
        exited = line.update([track(1, 40)], (100, 100, 3), 3)

        self.assertEqual(entered[0].event_type, "entry")
        self.assertEqual(exited[0].event_type, "exit")

    def test_fifo_visit_is_persisted_without_employee_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            repository = Repository(Path(temporary) / "visits.db")
            recorder = AccessRecorder(repository, "run-1")
            started = datetime(2026, 8, 10, 12, tzinfo=timezone.utc)

            recorder.observe(
                "cam07", AccessEvent("entry", "12", 0.8), started
            )
            result = recorder.observe(
                "cam07",
                AccessEvent("exit", "45", 0.8),
                started + timedelta(minutes=7),
            )
            visit = repository.query(
                "SELECT * FROM anonymous_visits"
            )[0]
            repository.close()

        self.assertTrue(result["paired"])
        self.assertEqual(visit["status"], "completed")
        self.assertAlmostEqual(visit["duration_seconds"], 420, delta=0.1)
        self.assertNotIn("employee", visit)


if __name__ == "__main__":
    unittest.main()
