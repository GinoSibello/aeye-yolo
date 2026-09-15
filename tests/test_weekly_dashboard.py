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
        self.assertIn('id="report-help"', html)
        self.assertIn("<summary>Cómo leer este informe</summary>", html)
        self.assertIn("Cupos simultáneos esperados", html)
        self.assertIn("Horas-persona faltantes", html)
        self.assertLess(
            html.index('id="report-help"'),
            html.index('id="weekly-view"'),
        )

    def test_help_explains_evidence_and_is_not_exported(self):
        html = (STATIC_DIR / "dashboard.html").read_text(encoding="utf-8")
        javascript = (STATIC_DIR / "dashboard.js").read_text(
            encoding="utf-8"
        )
        stylesheet = (STATIC_DIR / "dashboard.css").read_text(
            encoding="utf-8"
        )

        self.assertIn('aria-labelledby="help-data-title"', html)
        self.assertIn("Sin datos suficientes:", html)
        self.assertIn("no debe compararse directamente", html)
        self.assertIn("function measurementValue", javascript)
        self.assertIn("function eventEvidence", javascript)
        self.assertIn("jornadas completas", javascript)
        self.assertIn('"Sin datos suficientes"', javascript)
        self.assertIn('"No aplica"', javascript)
        self.assertIn(".report-help", stylesheet)
        print_block = stylesheet[stylesheet.index("@media print"):]
        self.assertIn(".report-help", print_block)

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
        self.assertIn("Cobertura calendario", javascript)
        self.assertIn("Duración media de todas las pausas", javascript)
        self.assertIn("async function downloadWeeklyImage", javascript)
        self.assertIn("canvas.toBlob", javascript)
        self.assertIn("document.body.append(link)", javascript)
        self.assertIn("Descarga iniciada", javascript)
        self.assertIn("window.print()", javascript)
        self.assertIn("function pdfFilename", javascript)
        self.assertIn(
            "Reporte_${periodName}_${compactDate(startValue)}_"
            "${compactDate(endValue)}.pdf",
            javascript,
        )
        self.assertIn("document.title = filename.slice(0, -4)", javascript)
        self.assertIn("document.title = printDocumentTitle", javascript)
        self.assertIn("function buildPrintCameraReports", javascript)
        self.assertIn("reportCameras(report).forEach", javascript)
        self.assertIn("renderCamera(row, report, target)", javascript)
        self.assertIn("window.addEventListener(\"afterprint\", clearPrintReport)", javascript)
        self.assertIn("#print-camera-reports", stylesheet)
        self.assertIn(".print-camera-sheet", stylesheet)
        self.assertIn("break-before: page", stylesheet)
        self.assertIn("@page", stylesheet)
        self.assertIn("size: A4 portrait", stylesheet)
        self.assertNotIn("size: A4 landscape", stylesheet)


if __name__ == "__main__":
    unittest.main()
