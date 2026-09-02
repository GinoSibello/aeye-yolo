"""Pruebas del estado y recursos del visor en vivo."""

import unittest
from pathlib import Path

from preview.state import build_preview_payload


PREVIEW_DIR = Path(__file__).resolve().parents[1] / "preview"


class PreviewUiTest(unittest.TestCase):
    def test_preview_payload_excludes_network_and_internal_fields(self):
        state = {
            "cam01": {
                "name": "Puesto uno",
                "zone": "Armado",
                "connected": True,
                "people": 2,
                "rule_state": "ok",
                "ip": "192.0.2.10",
                "track_ids": ["P001"],
                "last_error": "detalle interno",
            }
        }

        payload = build_preview_payload(state, True, refresh_ms=750)
        camera = payload["cameras"]["cam01"]

        self.assertTrue(payload["preview_enabled"])
        self.assertEqual(payload["refresh_ms"], 750)
        self.assertEqual(camera["people"], 2)
        self.assertNotIn("ip", camera)
        self.assertNotIn("track_ids", camera)
        self.assertNotIn("last_error", camera)

    def test_preview_assets_include_focus_and_return_controls(self):
        html = (PREVIEW_DIR / "index.html").read_text(encoding="utf-8")
        javascript = (PREVIEW_DIR / "preview.js").read_text(encoding="utf-8")
        stylesheet = (PREVIEW_DIR / "preview.css").read_text(encoding="utf-8")

        self.assertIn('id="back-to-grid"', html)
        self.assertIn("function focusCamera", javascript)
        self.assertIn("function clearFocus", javascript)
        self.assertIn('event.key === "Escape"', javascript)
        self.assertIn(".camera-card.is-focused", stylesheet)
        self.assertIn('aria-hidden="true"', stylesheet)


if __name__ == "__main__":
    unittest.main()

