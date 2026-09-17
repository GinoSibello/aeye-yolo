import json
import queue
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np

from metrics.reporting_config import capture_collection_window, within_work_shift
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


def collection_window(start, seconds=7200, identifier="window-0"):
    return {
        "id": identifier,
        "start": start,
        "end": start + timedelta(seconds=seconds),
        "duration_seconds": float(seconds),
    }


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
            "collection_window_minutes": 120.0,
            "quota_per_camera_per_window": 50,
            "queue_size": 64,
            "min_free_bytes": 0,
        }
        values.update(overrides)
        return DatasetCaptureSettings(**values)

    def collector(self, root, **overrides):
        session_id = overrides.pop("session_id", None)
        return DatasetCaptureCollector(
            self.settings(root, **overrides),
            engine="/models/private/yolo.engine",
            confidence=0.1,
            session_id=session_id,
        )

    def test_disabled_defaults_do_not_create_dataset(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "capture"
            settings = parse_dataset_capture_settings({})
            self.assertFalse(settings.enabled)
            self.assertEqual(settings.collection_window_minutes, 120.0)
            self.assertEqual(settings.quota_per_camera_per_window, 50)
            self.assertFalse(root.exists())

    def test_shift_windows_respect_timezone_boundaries_and_midnight(self):
        schedule = {
            "timezone": "America/Argentina/Buenos_Aires",
            "workdays": [0],
            "shifts": [
                {"id": "day", "start": "07:00", "end": "16:00"},
                {"id": "night", "start": "22:00", "end": "02:00"},
            ],
        }
        local = timezone(timedelta(hours=-3))
        monday_0700 = datetime(2026, 9, 14, 7, tzinfo=local)
        first = capture_collection_window(schedule, monday_0700)
        self.assertEqual(first["id"], "2026-09-14:day:0")
        self.assertEqual(first["end"].hour, 9)

        final = capture_collection_window(
            schedule, monday_0700 + timedelta(hours=8, minutes=30)
        )
        self.assertEqual(final["id"], "2026-09-14:day:4")
        self.assertEqual(final["duration_seconds"], 3600)
        self.assertIsNone(
            capture_collection_window(
                schedule, monday_0700 + timedelta(hours=9)
            )
        )

        monday_2200 = datetime(2026, 9, 14, 22, tzinfo=local)
        tuesday_0100 = monday_2200 + timedelta(hours=3)
        overnight = capture_collection_window(schedule, tuesday_0100)
        self.assertEqual(overnight["id"], "2026-09-14:night:1")
        self.assertTrue(within_work_shift(schedule, tuesday_0100))
        self.assertIsNone(
            capture_collection_window(schedule, monday_2200 + timedelta(hours=4))
        )

    def test_event_windows_reappearance_and_prolonged_sampling(self):
        with tempfile.TemporaryDirectory() as directory:
            collector = self.collector(directory)
            start = datetime(2026, 9, 14, 10, tzinfo=UTC)
            window = collection_window(start)
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
                    collection_window=window,
                )
            self.assertTrue(collector.wait_until_idle())
            collector.close()

            rows = metadata_rows(directory)
            reasons = [set(row["reason"].split("+")) for row in rows]
            self.assertEqual(
                sum("pre_context" in reason for reason in reasons), 3
            )
            self.assertTrue(any("presence_start" in reason for reason in reasons))
            self.assertTrue(
                any("presence_reappeared" in reason for reason in reasons)
            )
            self.assertTrue(
                any("presence_prolonged" in reason for reason in reasons)
            )
            self.assertEqual(
                sum("post_context" in reason for reason in reasons), 6
            )
            event_ids = {
                row["event_id"] for row in rows if row["event_id"] is not None
            }
            self.assertEqual(len(event_ids), 1)
            start_row = next(
                row for row in rows if "presence_start" in row["reason"]
            )
            self.assertEqual(start_row["engine"], "yolo.engine")
            self.assertEqual(start_row["confidence"], 0.1)
            self.assertEqual(start_row["boxes"][0]["confidence"], 0.8)
            self.assertEqual(start_row["collection_window_id"], "window-0")
            self.assertNotIn("ip", start_row)
            self.assertNotIn("username", start_row)

    def test_scheduled_samples_fill_quota_then_resume_next_window(self):
        with tempfile.TemporaryDirectory() as directory:
            collector = self.collector(
                directory,
                quota_per_camera_per_window=3,
                audit_interval_seconds=300,
            )
            start = datetime(2026, 9, 14, 10, tzinfo=UTC)
            first = collection_window(start, seconds=6, identifier="first")
            for seq, seconds in enumerate((0, 2, 4, 5), 1):
                collector.observe(
                    "cam01",
                    seq,
                    start + timedelta(seconds=seconds),
                    frame(seq),
                    [],
                    collection_window=first,
                )
            self.assertTrue(collector.wait_until_idle())
            self.assertEqual(len(metadata_rows(directory)), 3)

            second_start = start + timedelta(seconds=6)
            second = collection_window(
                second_start, seconds=6, identifier="second"
            )
            collector.observe(
                "cam01",
                5,
                second_start,
                frame(5),
                [],
                collection_window=second,
            )
            self.assertTrue(collector.wait_until_idle())
            status = collector.snapshot()
            collector.close()

            rows = metadata_rows(directory)
            self.assertEqual(len(rows), 4)
            self.assertEqual(
                sum(row["collection_window_id"] == "first" for row in rows), 3
            )
            self.assertEqual(
                sum(row["collection_window_id"] == "second" for row in rows), 1
            )
            self.assertEqual(
                status["saved_by_window"]["cam01|first"], 3
            )

    def test_outside_shift_does_not_buffer_or_save(self):
        with tempfile.TemporaryDirectory() as directory:
            collector = self.collector(directory)
            at = datetime(2026, 9, 14, 10, tzinfo=UTC)
            collector.observe(
                "cam01", 1, at, frame(1), [detection()], collection_window=None
            )
            self.assertTrue(collector.wait_until_idle())
            collector.close()
            self.assertEqual(metadata_rows(directory), [])

    def test_frame_hash_and_window_quota_survive_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            start = datetime(2026, 9, 14, 10, tzinfo=UTC)
            first = collection_window(start, identifier="first")
            collector = self.collector(
                directory, quota_per_camera_per_window=2, session_id="session-a"
            )
            collector.observe(
                "cam01", 1, start, frame(1), [detection()], first
            )
            collector.observe(
                "cam01",
                2,
                start + timedelta(seconds=10),
                frame(2),
                [detection()],
                first,
            )
            self.assertTrue(collector.wait_until_idle())
            collector.close()
            self.assertEqual(len(metadata_rows(directory)), 2)

            restarted = self.collector(
                directory, quota_per_camera_per_window=2, session_id="session-b"
            )
            restarted.observe(
                "cam01",
                1,
                start + timedelta(seconds=20),
                frame(3),
                [detection()],
                first,
            )
            second = collection_window(
                start + timedelta(hours=2), identifier="second"
            )
            restarted.observe(
                "cam01",
                2,
                start + timedelta(hours=2),
                frame(1),
                [detection()],
                second,
            )
            self.assertTrue(restarted.wait_until_idle())
            restarted.observe(
                "cam01",
                3,
                start + timedelta(hours=2, seconds=1),
                frame(4),
                [detection()],
                second,
            )
            self.assertTrue(restarted.wait_until_idle())
            status = restarted.snapshot()
            restarted.close()

            self.assertEqual(len(metadata_rows(directory)), 3)
            self.assertGreaterEqual(status["quota_reached"], 1)
            self.assertEqual(status["duplicate_hash"], 1)

    def test_legacy_index_is_loaded_without_blocking_new_windows(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            at = datetime(2026, 9, 14, 8, tzinfo=UTC)
            legacy = {
                "camera_id": "cam01",
                "sha256": "0" * 64,
                "session_id": "legacy-session",
                "frame_seq": 1,
                "timestamp": at.isoformat(),
                "reason": "audit",
            }
            (root / "capture_index.jsonl").write_text(
                json.dumps(legacy) + "\n", encoding="utf-8"
            )
            collector = self.collector(
                directory, quota_per_camera_per_window=1
            )
            collector.observe(
                "cam01",
                2,
                at + timedelta(hours=2),
                frame(2),
                [],
                collection_window(
                    at + timedelta(hours=2), identifier="new-window"
                ),
            )
            self.assertTrue(collector.wait_until_idle())
            status = collector.snapshot()
            collector.close()
            self.assertEqual(status["saved_by_window"]["cam01|legacy"], 1)
            self.assertEqual(status["saved_by_window"]["cam01|new-window"], 1)

    def test_full_queue_drops_without_disabling_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            collector = self.collector(directory, queue_size=1)
            collector._queue.put_nowait = mock.Mock(side_effect=queue.Full)
            at = datetime(2026, 9, 14, 10, tzinfo=UTC)
            collector.observe(
                "cam01",
                1,
                at,
                frame(1),
                [detection()],
                collection_window(at),
            )
            status = collector.snapshot()
            collector.close()
            self.assertTrue(status["enabled"])
            self.assertEqual(status["queue_full"], 1)

    def test_low_disk_stops_capture_and_records_reason(self):
        with tempfile.TemporaryDirectory() as directory:
            collector = self.collector(directory, min_free_bytes=10)
            disk = SimpleNamespace(total=100, used=95, free=5)
            at = datetime(2026, 9, 14, 10, tzinfo=UTC)
            with mock.patch(
                "vision.dataset_capture.shutil.disk_usage", return_value=disk
            ):
                collector.observe(
                    "cam01",
                    1,
                    at,
                    frame(1),
                    [detection()],
                    collection_window(at),
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
            at = datetime(2026, 9, 14, 10, tzinfo=UTC)
            with mock.patch(
                "vision.dataset_capture.cv2.imencode",
                return_value=(False, None),
            ):
                collector.observe(
                    "cam01",
                    1,
                    at,
                    frame(1),
                    [detection()],
                    collection_window(at),
                )
                self.assertTrue(collector.wait_until_idle())
            status = collector.snapshot()
            collector.close()
            self.assertFalse(status["enabled"])
            self.assertIn("OpenCV no pudo codificar JPEG", status["disabled_reason"])


if __name__ == "__main__":
    unittest.main()
