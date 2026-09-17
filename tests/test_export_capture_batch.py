import hashlib
import tempfile
import unittest
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from tools.export_capture_batch import build_incremental_archive
from vision.dataset_capture import DatasetCaptureCollector, DatasetCaptureSettings
from vision.detector import Detection


class ExportCaptureBatchTests(unittest.TestCase):
    def _collector(self, root):
        return DatasetCaptureCollector(
            DatasetCaptureSettings(
                enabled=True,
                root=Path(root),
                quota_per_camera_per_window=10,
                min_free_bytes=0,
            ),
            engine="yolo.engine",
            confidence=0.1,
        )

    def _save(self, collector, seq, at, value):
        collector.observe(
            "cam01",
            seq,
            at,
            np.full((16, 16, 3), value, dtype=np.uint8),
            [Detection([1, 1, 8, 14], 0.8, 0)],
            collection_window={
                "id": "export-window",
                "start": at.replace(minute=0, second=0, microsecond=0),
                "end": at.replace(minute=0, second=0, microsecond=0)
                + timedelta(hours=2),
                "duration_seconds": 7200.0,
            },
        )

    def test_incremental_zip_contains_new_images_manifest_and_checksums(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            at = datetime(2026, 9, 14, 10, tzinfo=timezone.utc)
            collector = self._collector(root)
            self._save(collector, 1, at, 20)
            self._save(collector, 2, at + timedelta(seconds=10), 40)
            self.assertTrue(collector.wait_until_idle())
            collector.close()

            first_output = root / "batch1.zip"
            first = build_incremental_archive(root, output=first_output)
            self.assertEqual(first["captures"], 2)
            archive_hash = hashlib.sha256(first_output.read_bytes()).hexdigest()
            self.assertTrue(
                first["checksum"].read_text(encoding="utf-8").startswith(
                    archive_hash
                )
            )
            with zipfile.ZipFile(first_output) as archive:
                names = archive.namelist()
                self.assertIn("manifest.jsonl", names)
                self.assertIn("SHA256SUMS", names)
                self.assertEqual(
                    len([name for name in names if name.endswith(".jpg")]), 2
                )
                self.assertEqual(
                    len([name for name in names if name.endswith(".json")]), 2
                )

            self.assertIsNone(
                build_incremental_archive(root, output=root / "empty.zip")
            )

            restarted = self._collector(root)
            self._save(restarted, 1, at + timedelta(hours=1), 60)
            self.assertTrue(restarted.wait_until_idle())
            restarted.close()

            second_output = root / "batch2.zip"
            second = build_incremental_archive(root, output=second_output)
            self.assertEqual(second["captures"], 1)
            with zipfile.ZipFile(second_output) as archive:
                self.assertEqual(
                    len([
                        name for name in archive.namelist()
                        if name.endswith(".jpg")
                    ]),
                    1,
                )


if __name__ == "__main__":
    unittest.main()
