import json
import queue
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np

from metrics.reporting_config import within_work_shift
from vision.dataset_capture import (
    DatasetCaptureCollector,
    DatasetCaptureSettings,
    parse_dataset_capture_settings,
)
from vision.detector import Detection


UTC = timezone.utc


def frame(value):
    return np.full((24, 32, 3), value, dtype=np.uint8)


def detection(confidence=0.8):
    return Detection([2.0, 3.0, 12.0, 20.0], confidence, 0)


def metadata_rows(root):
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((Path(root) / "metadata").glob("*/*.json"))
    ]


class DatasetCaptureTests(unittest.TestCase):
    def settings(self, root, **overrides):
        values = {
            "enabled": True,
            "root": Path(root),
            "sample_fps": 2.0,
            "pre_seconds": 2.0,
            "post_seconds": 2.0,
            "prolonged_interval_seconds": 10.0,
            "audit_interval_seconds": 300.0,
            "quota_per_camera": 500,
            "queue_size": 64,
            "min_free_bytes": 0,
        }
        values.update(overrides)
        return DatasetCaptureSettings(**values)

    def collector(self, root, **overrides):
        return DatasetCaptureCollector(
            self.settings(root, **overrides),
            engine="/models/private/yolo.engine",
            confidence=0.1,
            session_id=overrides.pop("session_id", None),
        )

    def test_disabled_defaults_do_not_create_dataset(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "capture"
            settings = parse_dataset_capture_settings({})
            self.assertFalse(settings.enabled)
            self.assertFalse(root.exists())

    def test_event_windows_reappearance_and_prolonged_sampling(self):
        with tempfile.TemporaryDirectory() as directory:
            collector = self.collector(directory)
            start = datetime(2026, 9, 14, 10, tzinfo=UTC)
            observations = [
                (0.0, []),
                (0.5, []),
                (1.0, []),
                (1.5, []),
                (2.0, [detection()]),
                (2.5, []),
                (3.0, []),
                (3.5, []),
                (3.9, [detection(0.75)]),
                (13.9, [detection(0.7)]),
                (14.4, []),
                (14.9, []),
                (15.4, []),
                (15.9, []),
            ]
            for seq, (seconds, detections) in enumerate(observations, 1):
                collector.observe(
                    "cam01",
                    seq,
                    start + timedelta(seconds=seconds),
                    frame(seq),
                    detections,
                    audit_allowed=False,
                )
            self.assertTrue(collector.wait_until_idle())
            collector.close()

            rows = metadata_rows(directory)
            reasons = [row["reason"] for row in rows]
            self.assertEqual(reasons.count("pre_context"), 4)
            self.assertIn("presence_start", reasons)
            self.assertIn("presence_reappeared", reasons)
            self.assertIn("presence_prolonged", reasons)
            self.assertEqual(reasons.count("post_context"), 6)
            event_ids = {
                row["event_id"] for row in rows if row["event_id"] is not None
            }
            self.assertEqual(len(event_ids), 1)
            start_row = next(row for row in rows if row["reason"] == "presence_start")
            self.assertEqual(start_row["engine"], "yolo.engine")
            self.assertEqual(start_row["confidence"], 0.1)
            self.assertEqual(start_row["boxes"][0]["confidence"], 0.8)
            self.assertNotIn("ip", start_row)
            self.assertNotIn("username", start_row)

    def test_audit_respects_workday_overnight_shift_and_interval(self):
        schedule = {
            "timezone": "America/Argentina/Buenos_Aires",
            "workdays": [0],
            "shifts": [{"start": "22:00", "end": "02:00"}],
        }
        monday = datetime(2026, 9, 14, tzinfo=timezone.utc)
        monday_2200 = datetime(2026, 9, 14, 22, tzinfo=timezone(
            timedelta(hours=-3)
        ))
        tuesday_0100 = monday_2200 + timedelta(hours=3)
        tuesday_2200 = monday_2200 + timedelta(days=1)
        self.assertTrue(within_work_shift(schedule, monday_2200))
        self.assertTrue(within_work_shift(schedule, tuesday_0100))
        self.assertFalse(within_work_shift(schedule, tuesday_2200))
        self.assertEqual(monday.weekday(), 0)

        with tempfile.TemporaryDirectory() as directory:
            collector = self.collector(directory)
            times = [
                monday_2200 - timedelta(seconds=1),
                monday_2200,
                monday_2200 + timedelta(seconds=299),
                monday_2200 + timedelta(seconds=300),
            ]
            for seq, at in enumerate(times, 1):
                collector.observe(
                    "cam01",
                    seq,
                    at,
                    frame(seq),
                    [],
                    audit_allowed=within_work_shift(schedule, at),
                )
            self.assertTrue(collector.wait_until_idle())
            collector.close()
            rows = metadata_rows(directory)
            self.assertEqual([row["reason"] for row in rows], ["audit", "audit"])

            restarted = self.collector(directory)
            at = monday_2200 + timedelta(seconds=301)
            restarted.observe(
                "cam01",
                1,
                at,
                frame(99),
                [],
                audit_allowed=within_work_shift(schedule, at),
            )
            self.assertTrue(restarted.wait_until_idle())
            restarted.close()
            self.assertEqual(len(metadata_rows(directory)), 2)

    def test_overlapping_reasons_frame_key_and_sha_are_deduplicated(self):
        with tempfile.TemporaryDirectory() as directory:
            collector = self.collector(directory)
            at = datetime(2026, 9, 14, 10, tzinfo=UTC)
            collector.observe(
                "cam01", 7, at, frame(7), [detection()], audit_allowed=True
            )
            collector.observe(
                "cam01", 7, at, frame(7), [detection()], audit_allowed=True
            )
            self.assertTrue(collector.wait_until_idle())
            first_status = collector.snapshot()
            collector.close()
            rows = metadata_rows(directory)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["reason"], "audit+presence_start")
            self.assertGreaterEqual(first_status["duplicate_frame"], 0)

            restarted = self.collector(directory)
            restarted.observe(
                "cam01",
                1,
                at + timedelta(hours=1),
                frame(7),
                [detection()],
                audit_allowed=False,
            )
            self.assertTrue(restarted.wait_until_idle())
            status = restarted.snapshot()
            restarted.close()
            self.assertEqual(len(metadata_rows(directory)), 1)
            self.assertEqual(status["duplicate_hash"], 1)

    def test_quota_is_persistent_across_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            collector = self.collector(directory, quota_per_camera=2)
            at = datetime(2026, 9, 14, 10, tzinfo=UTC)
            collector.observe(
                "cam01", 1, at, frame(1), [detection()], audit_allowed=False
            )
            collector.observe(
                "cam01",
                2,
                at + timedelta(seconds=10),
                frame(2),
                [detection()],
                audit_allowed=False,
            )
            self.assertTrue(collector.wait_until_idle())
            collector.close()
            self.assertEqual(len(metadata_rows(directory)), 2)

            restarted = self.collector(directory, quota_per_camera=2)
            restarted.observe(
                "cam01",
                1,
                at + timedelta(hours=1),
                frame(3),
                [detection()],
                audit_allowed=False,
            )
            self.assertTrue(restarted.wait_until_idle())
            status = restarted.snapshot()
            restarted.close()
            self.assertEqual(len(metadata_rows(directory)), 2)
            self.assertEqual(status["quota_reached"], 1)

    def test_full_queue_drops_without_disabling_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            collector = self.collector(directory, queue_size=1)
            collector._queue.put_nowait = mock.Mock(side_effect=queue.Full)
            collector.observe(
                "cam01",
                1,
                datetime(2026, 9, 14, 10, tzinfo=UTC),
                frame(1),
                [detection()],
                audit_allowed=False,
            )
            status = collector.snapshot()
            collector.close()
            self.assertTrue(status["enabled"])
            self.assertEqual(status["queue_full"], 1)

    def test_low_disk_stops_capture_and_records_reason(self):
        with tempfile.TemporaryDirectory() as directory:
            collector = self.collector(directory, min_free_bytes=10)
            disk = SimpleNamespace(total=100, used=95, free=5)
            with mock.patch(
                "vision.dataset_capture.shutil.disk_usage", return_value=disk
            ):
                collector.observe(
                    "cam01",
                    1,
                    datetime(2026, 9, 14, 10, tzinfo=UTC),
                    frame(1),
                    [detection()],
                    audit_allowed=False,
                )
                self.assertTrue(collector.wait_until_idle())
            status = collector.snapshot()
            collector.close()
            persisted = json.loads(
                (Path(directory) / "status.json").read_text(encoding="utf-8")
            )
            self.assertFalse(status["enabled"])
            self.assertTrue(status["disabled_reason"].startswith("low_disk:"))
            self.assertEqual(
                persisted["disabled_reason"], status["disabled_reason"]
            )

    def test_jpeg_write_error_stops_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            collector = self.collector(directory)
            with mock.patch(
                "vision.dataset_capture.cv2.imencode",
                return_value=(False, None),
            ):
                collector.observe(
                    "cam01",
                    1,
                    datetime(2026, 9, 14, 10, tzinfo=UTC),
                    frame(1),
                    [detection()],
                    audit_allowed=False,
                )
                self.assertTrue(collector.wait_until_idle())
            status = collector.snapshot()
            collector.close()
            self.assertFalse(status["enabled"])
            self.assertIn("OpenCV no pudo codificar JPEG", status["disabled_reason"])


if __name__ == "__main__":
    unittest.main()
