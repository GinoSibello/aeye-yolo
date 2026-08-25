import json
import tempfile
import unittest
from pathlib import Path

from metrics.performance import PerformanceMonitor
from tools.summarize_tegrastats import parse_lines


class FakeReader:
    def performance_snapshot(self):
        return {
            "received_frames": 10,
            "received_fps_active": 25.0,
            "connection_attempts": 3,
            "successful_connections": 2,
            "connection_errors": 1,
            "stream": {
                "width": 1920,
                "height": 1080,
                "reported_fps": 25.0,
                "codec": "h264",
            },
        }


class PerformanceTest(unittest.TestCase):
    def test_summary_tracks_skips_duplicates_percentiles_and_reconnections(self):
        monitor = PerformanceMonitor(["cam_test"])
        monitor.record_analysis("cam_test", 10, {"inference_ms": 10.0})
        monitor.record_analysis("cam_test", 13, {"inference_ms": 20.0})
        monitor.record_analysis("cam_test", 13, {"inference_ms": 30.0})

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "performance.json"
            monitor.write(path, {"cam_test": FakeReader()}, {"preview": False})
            summary = json.loads(path.read_text(encoding="utf-8"))

        camera = summary["cameras"]["cam_test"]
        inference = camera["timings_ms"]["inference_ms"]
        self.assertEqual(camera["unique_analyzed_frames"], 2)
        self.assertEqual(camera["scheduler_skipped_frames"], 2)
        self.assertEqual(camera["duplicate_analyses"], 1)
        self.assertEqual(camera["not_analyzed_frames_estimate"], 8)
        self.assertIsNotNone(camera["analyzed_fps_active"])
        self.assertGreater(camera["analyzed_fps_active"], 0)
        self.assertIsNotNone(camera["unique_analyzed_fps_active"])
        self.assertLess(
            camera["unique_analyzed_fps_active"], camera["analyzed_fps_active"]
        )
        self.assertEqual(camera["reconnections"], 1)
        self.assertEqual(inference["p50"], 20.0)
        self.assertEqual(inference["p95"], 29.0)

    def test_r39_tegrastats_format_preserves_reported_power_peak(self):
        line = (
            "RAM 3703/7485MB (lfb 30x4MB) "
            "CPU [30%@729,0%@729,18%@729,9%@729,0%@729,0%@729] "
            "GR3D_FREQ 7% cpu@49.812C/49.812C gpu@49.187C/49.343C "
            "VDD_IN 5064mW/5117mW/5184mW"
        )
        fragmented = "RAM 4727/7485MB (lfb 3x512kB)"
        summary = parse_lines([line, fragmented])
        self.assertEqual(summary["parsed_samples"], 2)
        self.assertEqual(summary["gpu_percent"]["max"], 7.0)
        self.assertEqual(summary["maximum_temperature_c"], 49.812)
        self.assertEqual(summary["power_vdd_in_mw"]["avg"], 5064.0)
        self.assertEqual(summary["power_vdd_in_reported_peak_mw"], 5184.0)
        self.assertIsNone(summary["nvdec_percent"]["avg"])
        self.assertEqual(summary["ram_used_mb"]["samples"], 2)
        self.assertEqual(summary["largest_free_block"]["minimum_block_mb"], 0.5)

        self.assertEqual(
            summary["largest_free_block"]["blocks_at_minimum_block_size"], 3
        )
        self.assertEqual(summary["largest_free_block"]["minimum_total_mb"], 1.5)

if __name__ == "__main__":
    unittest.main()
