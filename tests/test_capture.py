import unittest
from unittest.mock import Mock, patch

from vision.capture import (
    CaptureBackendUnavailable,
    build_nvdec_pipeline,
    open_capture,
    parse_capture_settings,
)


class CaptureTest(unittest.TestCase):
    def test_default_backend_preserves_ffmpeg(self):
        settings = parse_capture_settings({})
        self.assertEqual(settings.backend, "ffmpeg")
        self.assertTrue(settings.fallback_to_ffmpeg)

    def test_nvdec_pipeline_selects_h265_without_embedding_url(self):
        settings = parse_capture_settings(
            {
                "backend": "nvdec",
                "codec": "hevc",
                "rtsp_latency_ms": 125,
            }
        )
        pipeline = build_nvdec_pipeline(settings)
        self.assertEqual(settings.backend, "gstreamer_nvdec")
        self.assertIn("rtph265depay ! h265parse ! nvv4l2decoder", pipeline)
        self.assertIn("latency=125", pipeline)
        self.assertIn("max-buffers=1 drop=true", pipeline)
        self.assertNotIn("rtsp://", pipeline)

    def test_nvdec_pipeline_supports_h264(self):
        settings = parse_capture_settings(
            {"backend": "gstreamer_nvdec", "codec": "h264"}
        )
        self.assertIn(
            "rtph264depay ! h264parse ! nvv4l2decoder",
            build_nvdec_pipeline(settings),
        )

    def test_unavailable_nvdec_uses_configured_fallback(self):
        fallback = Mock()
        with patch(
            "vision.capture.GStreamerNvdecCapture",
            side_effect=CaptureBackendUnavailable("plugin ausente"),
        ), patch("vision.capture.FFmpegCapture", return_value=fallback):
            result = open_capture(
                "rtsp://example.invalid/stream",
                {"backend": "nvdec", "fallback_to_ffmpeg": True},
            )
        self.assertIs(result, fallback)
        self.assertEqual(result.fallback_reason, "plugin ausente")

    def test_runtime_fallback_keeps_an_auditable_reason(self):
        fallback = Mock()
        with patch("vision.capture.FFmpegCapture", return_value=fallback):
            result = open_capture(
                "rtsp://example.invalid/stream",
                {"backend": "nvdec", "fallback_to_ffmpeg": True},
                force_ffmpeg=True,
            )
        self.assertIs(result, fallback)
        self.assertIn("GStreamer NVDEC", result.fallback_reason)

    def test_unavailable_nvdec_can_fail_closed(self):
        with patch(
            "vision.capture.GStreamerNvdecCapture",
            side_effect=CaptureBackendUnavailable("plugin ausente"),
        ):
            with self.assertRaises(CaptureBackendUnavailable):
                open_capture(
                    "rtsp://example.invalid/stream",
                    {"backend": "nvdec", "fallback_to_ffmpeg": False},
                )

    def test_invalid_codec_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_capture_settings({"codec": "mpeg2"})


if __name__ == "__main__":
    unittest.main()
