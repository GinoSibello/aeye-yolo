import json
import queue
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np

from vision.alert_evidence import (
    AlertEvidenceCollector,
    AlertEvidenceSettings,
    parse_alert_evidence_settings,
)


UTC = timezone.utc


def image(value):
    return np.full((20, 28, 3), value, dtype=np.uint8)


def alert(camera_id="cam01", kind="missing"):
    return {
        "kind": kind,
        "camera_id": camera_id,
        "camera_name": "Puesto de prueba",
        "reason": "faltantes" if kind == "missing" else "sobrantes",
        "raw_people": 0,
        "people": 0,
        "expected_min": 2,
        "expected_max": 2,
        "outside_range_seconds": 900,
    }


def manifests(root):
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(Path(root).glob("????-??-??/*/manifest.json"))
    ]


class AlertEvidenceTests(unittest.TestCase):
    def settings(self, root, **overrides):
        values = {
            "enabled": True,
            "root": Path(root),
            "sample_fps": 1.0,
            "pre_seconds": 3.0,
            "post_seconds": 3.0,
            "jpeg_quality": 92,
            "input_queue_size": 128,
            "write_queue_size": 512,
            "retention_days": 30,
            "min_free_bytes": 0,
            "cleanup_target_free_bytes": 0,
        }
        values.update(overrides)
        return AlertEvidenceSettings(**values)

    def collector(self, root, **overrides):
        return AlertEvidenceCollector(self.settings(root, **overrides))

    def observe(self, collector, camera_id, seq, at, value, event=None):
        return collector.observe(
            camera_id,
            seq,
            at,
            image(value),
            raw_people=0,
            people=0,
            alert=event,
            monitoring=True,
        )

    def test_defaults_are_disabled_and_do_not_create_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "evidence"
            settings = parse_alert_evidence_settings(
                {}, project_dir=directory
            )
            self.assertFalse(settings.enabled)
            self.assertEqual(settings.sample_fps, 1.0)
            self.assertEqual(settings.expected_frames, 60)
            self.assertFalse(root.exists())

    def test_exact_pre_and_post_window_at_one_fps(self):
        with tempfile.TemporaryDirectory() as directory:
            collector = self.collector(directory)
            alert_at = datetime.now(tz=UTC) + timedelta(seconds=2)
            for seq, offset in enumerate((-3, -2, -1), 1):
                self.observe(
                    collector, "cam01", seq,
                    alert_at + timedelta(seconds=offset), seq,
                )
            descriptor = self.observe(
                collector, "cam01", 4, alert_at, 4, alert("cam01")
            )
            self.assertEqual(descriptor["status"], "collecting")
            for seq, offset in enumerate((1, 2, 3), 5):
                self.observe(
                    collector, "cam01", seq,
                    alert_at + timedelta(seconds=offset), seq,
                )
            self.assertTrue(collector.wait_until_idle())
            collector.close()

            rows = manifests(directory)
            self.assertEqual(len(rows), 1)
            manifest = rows[0]
            self.assertEqual(manifest["status"], "complete")
            self.assertEqual(manifest["frame_count"], 6)
            self.assertEqual(
                [row["relative_seconds"] for row in manifest["frames"]],
                [-3.0, -2.0, -1.0, 0.0, 1.0, 2.0],
            )
            self.assertEqual(manifest["coverage_percent"], 100.0)
            self.assertNotIn("ip", manifest)
            self.assertNotIn("track_ids", manifest)

    def test_sampling_skips_subsecond_frames_and_stale_prebuffer(self):
        with tempfile.TemporaryDirectory() as directory:
            collector = self.collector(directory, pre_seconds=2, post_seconds=1)
            alert_at = datetime.now(tz=UTC) + timedelta(seconds=2)
            self.observe(
                collector, "cam01", 1,
                alert_at - timedelta(seconds=100), 1,
            )
            self.observe(
                collector, "cam01", 2,
                alert_at - timedelta(seconds=1), 2,
            )
            self.observe(
                collector, "cam01", 3,
                alert_at - timedelta(milliseconds=500), 3,
            )
            self.observe(
                collector, "cam01", 4, alert_at, 4, alert("cam01")
            )
            self.observe(
                collector, "cam01", 5,
                alert_at + timedelta(seconds=1), 5,
            )
            self.assertTrue(collector.wait_until_idle())
            collector.close()

            manifest = manifests(directory)[0]
            self.assertEqual(
                [row["relative_seconds"] for row in manifest["frames"]],
                [-1.0, 0.0],
            )
            self.assertLess(manifest["coverage_percent"], 100.0)

    def test_extra_alert_does_not_create_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            collector = self.collector(directory)
            at = datetime.now(tz=UTC)
            descriptor = self.observe(
                collector, "cam01", 1, at, 1, alert("cam01", "extra")
            )
            self.assertIsNone(descriptor)
            self.assertTrue(collector.wait_until_idle())
            collector.close()
            self.assertEqual(manifests(directory), [])

    def test_cameras_keep_independent_buffers(self):
        with tempfile.TemporaryDirectory() as directory:
            collector = self.collector(directory, pre_seconds=1, post_seconds=1)
            at = datetime.now(tz=UTC) + timedelta(seconds=1)
            self.observe(collector, "cam01", 1, at, 1, alert("cam01"))
            self.observe(collector, "cam02", 1, at, 2, alert("cam02"))
            self.observe(
                collector, "cam01", 2, at + timedelta(seconds=1), 3
            )
            self.observe(
                collector, "cam02", 2, at + timedelta(seconds=1), 4
            )
            self.assertTrue(collector.wait_until_idle())
            collector.close()
            rows = manifests(directory)
            self.assertEqual({row["camera_id"] for row in rows}, {"cam01", "cam02"})

    def test_input_queue_full_does_not_block_and_marks_descriptor_failed(self):
        with tempfile.TemporaryDirectory() as directory:
            collector = self.collector(directory)
            collector._input_queue.put_nowait = mock.Mock(side_effect=queue.Full)
            descriptor = self.observe(
                collector,
                "cam01",
                1,
                datetime.now(tz=UTC),
                1,
                alert("cam01"),
            )
            status = collector.snapshot()
            collector.close()
            self.assertEqual(descriptor["status"], "failed")
            self.assertEqual(status["input_queue_full"], 1)

    def test_writer_queue_full_is_counted_without_waiting(self):
        with tempfile.TemporaryDirectory() as directory:
            collector = self.collector(directory)
            collector._write_queue.put_nowait = mock.Mock(
                side_effect=queue.Full
            )
            self.assertFalse(collector._enqueue_writer(object()))
            self.assertEqual(collector.snapshot()["write_queue_full"], 1)
            collector.close()

    def test_write_failure_isolated_from_observe(self):
        with tempfile.TemporaryDirectory() as directory:
            collector = self.collector(directory)
            with mock.patch(
                "vision.alert_evidence._atomic_json",
                side_effect=OSError("disco de prueba"),
            ):
                descriptor = self.observe(
                    collector, "cam01", 1,
                    datetime.now(tz=UTC) + timedelta(seconds=2),
                    1, alert("cam01"),
                )
                self.assertEqual(descriptor["status"], "collecting")
                self.assertTrue(collector.wait_until_idle())
            self.assertGreaterEqual(collector.snapshot()["write_errors"], 1)
            collector.close()

    def test_restart_marks_collecting_manifest_interrupted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            event_dir = root / "2026-09-16" / ("a" * 32)
            event_dir.mkdir(parents=True)
            (event_dir / "manifest.json").write_text(
                json.dumps({
                    "evidence_id": "a" * 32,
                    "alert_at": "2026-09-16T10:00:00+00:00",
                    "status": "collecting",
                }),
                encoding="utf-8",
            )
            collector = self.collector(directory)
            collector.close()
            manifest = json.loads(
                (event_dir / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["status"], "interrupted")
            self.assertEqual(manifest["failure_reason"], "process_restart")

    def test_close_during_capture_marks_event_interrupted(self):
        with tempfile.TemporaryDirectory() as directory:
            collector = self.collector(directory)
            self.observe(
                collector, "cam01", 1,
                datetime.now(tz=UTC) + timedelta(seconds=5),
                1, alert("cam01"),
            )
            self.assertTrue(collector.wait_until_idle())
            self.assertTrue(collector.close())
            manifest = manifests(directory)[0]
            self.assertEqual(manifest["status"], "interrupted")

    def test_retention_removes_only_expired_completed_events(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            now = datetime.now(tz=UTC)
            old = self._write_manifest(root, "a" * 32, now - timedelta(days=31))
            recent = self._write_manifest(root, "b" * 32, now - timedelta(days=1))
            active = self._write_manifest(
                root, "c" * 32, now, status="collecting"
            )
            interrupted = self._write_manifest(
                root, "d" * 32, now - timedelta(days=40), status="interrupted"
            )
            failed = self._write_manifest(
                root, "e" * 32, now - timedelta(days=40), status="failed"
            )
            collector = self.collector(directory)
            collector.close()
            self.assertFalse(old.exists())
            self.assertTrue(recent.exists())
            self.assertTrue(active.exists())
            self.assertTrue(interrupted.exists())
            self.assertTrue(failed.exists())

    def test_low_disk_deletes_oldest_and_preserves_collecting(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            now = datetime.now(tz=UTC)
            oldest = self._write_manifest(root, "a" * 32, now - timedelta(days=3))
            recent = self._write_manifest(root, "b" * 32, now - timedelta(days=1))
            active = self._write_manifest(
                root, "c" * 32, now, status="collecting"
            )
            collector = self.collector(
                directory,
                min_free_bytes=5,
                cleanup_target_free_bytes=6,
            )
            disk = [
                SimpleNamespace(free=4),
                SimpleNamespace(free=7),
            ]
            with mock.patch(
                "vision.alert_evidence.shutil.disk_usage", side_effect=disk
            ):
                self.assertTrue(collector._ensure_space(set()))
            collector.close()
            self.assertFalse(oldest.exists())
            self.assertTrue(recent.exists())
            self.assertTrue(active.exists())

    def test_low_disk_without_deletable_events_returns_false(self):
        with tempfile.TemporaryDirectory() as directory:
            collector = self.collector(
                directory,
                min_free_bytes=5,
                cleanup_target_free_bytes=6,
            )
            with mock.patch(
                "vision.alert_evidence.shutil.disk_usage",
                return_value=SimpleNamespace(free=4),
            ):
                self.assertFalse(collector._ensure_space(set()))
            collector.close()

    def _write_manifest(self, root, evidence_id, alert_at, status="complete"):
        event_dir = root / alert_at.date().isoformat() / evidence_id
        event_dir.mkdir(parents=True)
        path = event_dir / "manifest.json"
        path.write_text(
            json.dumps({
                "evidence_id": evidence_id,
                "camera_id": "cam01",
                "alert_at": alert_at.isoformat(),
                "status": status,
                "frames": [],
            }),
            encoding="utf-8",
        )
        return path


if __name__ == "__main__":
    unittest.main()
