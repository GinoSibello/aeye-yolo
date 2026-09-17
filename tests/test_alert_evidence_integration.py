import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AlertEvidenceIntegrationTests(unittest.TestCase):
    def test_evidence_receives_successful_raw_inference_frame_before_overlay(self):
        source = (ROOT / "main.py").read_text(encoding="utf-8")
        detection = source.index("detections_by_frame, timings_by_frame = detect_batch(")
        evidence = source.index("evidence = alert_evidence_collector.observe(")
        overlay = source.index("annotated = draw_overlay(")

        self.assertLess(detection, evidence)
        self.assertLess(evidence, overlay)
        evidence_call = source[evidence:source.index(")", evidence) + 1]
        self.assertIn("frame,", evidence_call)
        self.assertNotIn("annotated", evidence_call)

    def test_legacy_alert_image_and_new_descriptor_are_both_sent(self):
        source = (ROOT / "main.py").read_text(encoding="utf-8")
        evidence = source.index('detail["evidence"] = evidence')
        legacy = source.index('detail["image_path"] = alert_image_path')
        send = source.index("send_alert(alert_cfg, detail)")

        self.assertLess(evidence, send)
        self.assertLess(legacy, send)


if __name__ == "__main__":
    unittest.main()
