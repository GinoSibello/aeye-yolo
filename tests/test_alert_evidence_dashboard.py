import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AlertEvidenceDashboardTests(unittest.TestCase):
    def test_dashboard_has_evidence_mode_and_player(self):
        html = (ROOT / "api/static/dashboard.html").read_text(encoding="utf-8")
        javascript = (ROOT / "api/static/dashboard.js").read_text(encoding="utf-8")
        css = (ROOT / "api/static/dashboard.css").read_text(encoding="utf-8")

        for marker in (
            'id="evidence-mode"',
            'id="evidence-view"',
            'id="evidence-dialog"',
            'id="evidence-play"',
            'id="evidence-range"',
            'id="evidence-thumbnails"',
        ):
            self.assertIn(marker, html)
        self.assertIn("/api/alert-evidence?day=", javascript)
        self.assertIn("Cargando evidencias", javascript)
        self.assertIn("setInterval", javascript)
        self.assertIn("detail.status === \"collecting\"", javascript)
        self.assertIn("#evidence-view", css)
        self.assertIn(".evidence-dialog", css)

    def test_evidence_is_excluded_from_report_exports(self):
        javascript = (ROOT / "api/static/dashboard.js").read_text(encoding="utf-8")
        css = (ROOT / "api/static/dashboard.css").read_text(encoding="utf-8")

        self.assertIn('elements.image.classList.toggle(\n    "hidden", evidenceMode', javascript)
        self.assertIn('elements.pdf.classList.toggle(\n    "hidden", evidenceMode', javascript)
        print_block = css.split("@media print", 1)[1]
        self.assertIn("#evidence-view", print_block)
        self.assertIn(".evidence-dialog", print_block)


if __name__ == "__main__":
    unittest.main()
