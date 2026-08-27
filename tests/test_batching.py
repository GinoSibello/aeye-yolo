import unittest

from vision.batching import BatchScheduler, parse_batching_settings


class BatchingTest(unittest.TestCase):
    def test_disabled_batching_preserves_single_frame_calls(self):
        settings = parse_batching_settings({})
        self.assertFalse(settings.enabled)
        self.assertEqual(settings.max_batch_size, 1)
        self.assertEqual(settings.timeout_ms, 0)

    def test_enabled_batching_uses_explicit_limits(self):
        settings = parse_batching_settings({
            "batching": {
                "enabled": True,
                "max_batch_size": 8,
                "timeout_ms": 10,
            }
        })
        self.assertTrue(settings.enabled)
        self.assertEqual(settings.max_batch_size, 8)
        self.assertEqual(settings.timeout_ms, 10)

    def test_invalid_batching_limits_are_rejected(self):
        with self.assertRaises(ValueError):
            parse_batching_settings({
                "batching": {"enabled": True, "max_batch_size": 1}
            })
        with self.assertRaises(ValueError):
            parse_batching_settings({
                "batching": {
                    "enabled": True,
                    "max_batch_size": 8,
                    "timeout_ms": 1001,
                }
            })

    def test_scheduler_preserves_deadline_and_camera_order(self):
        settings = parse_batching_settings({
            "batching": {"enabled": True, "max_batch_size": 8, "timeout_ms": 10}
        })
        scheduler = BatchScheduler(["cam_a", "cam_b", "cam_c"], 2.0, settings)
        self.assertEqual(scheduler.due(100.0), ["cam_a", "cam_b", "cam_c"])
        lags = scheduler.schedule(["cam_a"], 100.0)
        self.assertEqual(lags["cam_a"], 0.0)
        self.assertEqual(scheduler.due(100.1), ["cam_b", "cam_c"])
        scheduler.schedule(["cam_b", "cam_c"], 100.1)
        self.assertEqual(scheduler.due(100.49), [])
        self.assertEqual(scheduler.due(100.5), ["cam_a"])

    def test_scheduler_wait_is_short_and_bounded_by_window(self):
        settings = parse_batching_settings({
            "batching": {"enabled": True, "max_batch_size": 8, "timeout_ms": 10}
        })
        scheduler = BatchScheduler(["cam_a"], 6.0, settings)
        scheduler.next_inference["cam_a"] = 100.008
        self.assertEqual(scheduler.window_deadline(100.0), 100.01)
        self.assertAlmostEqual(scheduler.wait_seconds(100.0, 100.01), 0.005)


if __name__ == "__main__":
    unittest.main()
