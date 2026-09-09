"""Pruebas de contrato de la interfaz del reporte semanal."""

import unittest
from pathlib import Path


STATIC_DIR = Path(__file__).resolve().parents[1] / "api" / "static"


class WeeklyDashboardTest(unittest.TestCase):
    def test_weekly_view_exposes_report_and_export_controls(self):
        html = (STATIC_DIR / "dashboard.html").read_text(encoding="utf-8")

        self.assertIn('id="monthly-mode"', html)
        self.assertIn('id="scope-tabs"', html)
        self.assertIn('id="camera-view"', html)
        self.assertIn('id="weekly-view"', html)
        self.assertIn('id="weekly-sheet"', html)
        self.assertIn('id="workstation-gauges"', html)
        self.assertIn('id="shift-quality"', html)
        self.assertIn('id="hourly-chart"', html)
        self.assertIn('id="image-download"', html)
        self.assertIn('id="pdf-print"', html)
        self.assertIn('id="download-status"', html)

    def test_weekly_script_uses_api_and_native_exports(self):
        javascript = (STATIC_DIR / "dashboard.js").read_text(
            encoding="utf-8"
        )
        stylesheet = (STATIC_DIR / "dashboard.css").read_text(
            encoding="utf-8"
        )

        self.assertIn("/api/reports/weekly?week=", javascript)
        self.assertIn("/api/reports/monthly?month=", javascript)
        self.assertIn("function renderCamera", javascript)
        self.assertIn("function renderShiftQuality", javascript)
        self.assertIn("coverage >= 95", javascript)
        self.assertIn("function eventComparisonMarkup", javascript)
        self.assertIn("function gaugeMarkup", javascript)
        self.assertIn("async function downloadWeeklyImage", javascript)
        self.assertIn("canvas.toBlob", javascript)
        self.assertIn("document.body.append(link)", javascript)
        self.assertIn("Descarga iniciada", javascript)
        self.assertIn("window.print()", javascript)
        self.assertIn("@page", stylesheet)
        self.assertIn("size: A4 landscape", stylesheet)


if __name__ == "__main__":
    unittest.main()
