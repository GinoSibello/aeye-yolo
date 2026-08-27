import unittest

import numpy as np

from vision.pipeline import frame_snapshot, parse_pipeline_settings


class PipelineSettingsTest(unittest.TestCase):
    def test_shared_snapshot_is_read_only_without_copying_pixels(self):
        frame = np.zeros((2, 2, 3), dtype=np.uint8)
        snapshot = frame_snapshot(frame, copy_frame=False)
        self.assertTrue(np.shares_memory(frame, snapshot))
        self.assertFalse(snapshot.flags.writeable)
        with self.assertRaises(ValueError):
            snapshot[0, 0, 0] = 1

    def test_copied_snapshot_is_independent_and_writeable(self):
        frame = np.zeros((2, 2, 3), dtype=np.uint8)
        snapshot = frame_snapshot(frame, copy_frame=True)
        self.assertFalse(np.shares_memory(frame, snapshot))
        self.assertTrue(snapshot.flags.writeable)

    def test_defaults_preserve_historical_paths(self):
        settings = parse_pipeline_settings({})
        self.assertTrue(settings.copy_latest_frame)
        self.assertEqual(settings.result_transfer, "split")

    def test_optimized_paths_are_explicit(self):
        settings = parse_pipeline_settings({
            "pipeline": {
                "copy_latest_frame": False,
                "result_transfer": "packed",
            }
        })
        self.assertFalse(settings.copy_latest_frame)
        self.assertEqual(settings.result_transfer, "packed")

    def test_invalid_result_transfer_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "split o packed"):
            parse_pipeline_settings({"pipeline": {"result_transfer": "other"}})


if __name__ == "__main__":
    unittest.main()
