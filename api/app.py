"""Expone el dashboard y las consultas analiticas de AEYE mediante FastAPI."""

import csv
import io
import json
import os
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from database.repository import Repository
from metrics.activity import ActivityAnalytics
from metrics.analytics import Analytics
from metrics.reporting_config import sync_reporting_configuration
from metrics.weekly import WeeklyActivityAnalytics

PROJECT_DIR = Path(__file__).resolve().parents[1]
STATIC_DIR = Path(__file__).resolve().parent / "static"
CONFIG_PATH = Path(
    os.environ.get("AEYE_CONFIG", PROJECT_DIR / "cameras.json")
)
config = (
    json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if CONFIG_PATH.is_file() else {}
)
database_path = os.environ.get(
    "AEYE_DB_PATH",
    config.get("database", {}).get(
        "path", str(PROJECT_DIR / "data" / "aeye.db")
    ),
)
repository = Repository(database_path)
if config.get("cameras"):
    sync_reporting_configuration(repository, config)

analytics = Analytics(repository)
activity = ActivityAnalytics(repository)
weekly_activity = WeeklyActivityAnalytics(repository)
app = FastAPI(title="AEYE API", version="0.2.0")
app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")


def period(start, end):
    """Valida un intervalo temporal y devuelve extremos ISO 8601."""
    if end <= start:
        raise HTTPException(422, "end debe ser posterior a start")
    return start.isoformat(), end.isoformat()


def _value(row, *path):
    """Obtiene una metrica anidada sin convertir ausencia en cero."""
    current = row
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


@app.get("/", include_in_schema=False)
def dashboard():
    """Sirve la interfaz operativa de reportes."""
    return FileResponse(STATIC_DIR / "dashboard.html")


@app.get("/api/health")
def health():
    """Comprueba que la API puede consultar la base SQLite."""
    repository.query("SELECT 1")
    return {"status": "ok"}


@app.get("/api/analytics/understaffed-hours")
def understaffed_hours(zone: str, start: datetime, end: datetime):
    """Agrupa por hora el porcentaje de muestras debajo del minimo."""
    return analytics.understaffed_by_hour(zone, *period(start, end))


@app.get("/api/analytics/minutes-below-minimum")
def below(zone: str, start: datetime, end: datetime):
    """Calcula los minutos estimados por debajo de la dotacion minima."""
    return analytics.minutes_below_minimum(zone, *period(start, end))


@app.get("/api/analytics/employee-zone-time")
def employee_time(
    start: datetime, end: datetime, employee_id: Optional[str] = None
):
    """Resume sesiones por empleado y zona cuando existen identidades vinculadas."""
    return analytics.employee_time_by_zone(*period(start, end), employee_id)


@app.get("/api/analytics/transitions")
def transitions(
    start: datetime, end: datetime, limit: int = Query(20, ge=1, le=100)
):
    """Lista las transiciones entre zonas mas frecuentes del periodo."""
    return analytics.common_transitions(*period(start, end), limit)


@app.get("/api/analytics/long-incidents")
def incidents(
    start: datetime, end: datetime, minutes: float = Query(20, gt=0)
):
    """Cuenta incidentes cuya duracion supera el umbral indicado."""
    return analytics.long_incidents(*period(start, end), minutes)


@app.get("/api/analytics/false-positives")
def false_positives(
    start: datetime,
    end: datetime,
    minimum_reviews: int = Query(1, ge=1),
):
    """Calcula falsos positivos por camara a partir de revisiones humanas."""
    return analytics.false_positives_by_camera(
        *period(start, end), minimum_reviews
    )


@app.get("/api/analytics/occupancy-by-hour")
def occupancy(
    start: datetime, end: datetime, zone: Optional[str] = None
):
    """Devuelve ocupacion minima, maxima y promedio agrupada por hora."""
    return analytics.average_occupancy_by_hour(*period(start, end), zone)


@app.get("/api/reporting/configuration")
def reporting_configuration():
    """Lista la configuracion efectiva sin datos de conexion RTSP."""
    return activity.configuration()


@app.get("/api/reports/daily")
def daily_report(day: date = Query(default_factory=date.today)):
    """Devuelve ocupacion y estimaciones anonimas para un dia local."""
    return activity.daily_report(day)


@app.get("/api/reports/weekly")
def weekly_report(week: date = Query(default_factory=date.today)):
    """Devuelve un resumen de lunes a domingo para jefatura."""
    return weekly_activity.weekly_report(week)


@app.get("/api/reports/monthly")
def monthly_report(month: date = Query(default_factory=date.today)):
    """Devuelve un resumen del mes calendario para jefatura."""
    return weekly_activity.monthly_report(month)


@app.get("/api/reports/daily.csv")
def daily_report_csv(day: date = Query(default_factory=date.today)):
    """Exporta una fila por puesto para trabajar el reporte fuera de AEYE."""
    report = activity.daily_report(day)
    output = io.StringIO()
    fields = [
        "fecha", "camara", "puesto", "zona", "estado_configuracion",
        "horario", "personas_esperadas", "ocupacion_promedio",
        "cobertura_datos_pct", "dotacion_completa_pct",
        "horas_persona", "horas_persona_faltantes",
        "llegadas_tarde_estimadas", "promedio_tarde_min",
        "salidas_anticipadas_estimadas", "promedio_anticipacion_min",
        "salidas_despues_de_hora_estimadas", "promedio_extra_min",
        "pausas_estimadas", "pausas_excedidas_estimadas",
        "promedio_pausa_min",
    ]
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for row in report["workstations"]:
        writer.writerow({
            "fecha": report["date"],
            "camara": row["camera_id"],
            "puesto": row["name"],
            "zona": row["zone"],
            "estado_configuracion": row["configuration_status"],
            "horario": (
                f"{row['shift_start']}-{row['shift_end']}"
                if row["shift_start"] and row["shift_end"] else ""
            ),
            "personas_esperadas": row["expected_people"],
            "ocupacion_promedio": row["average_occupancy"],
            "cobertura_datos_pct": row["data_coverage_percent"],
            "dotacion_completa_pct": row["staffing_coverage_percent"],
            "horas_persona": row["person_hours"],
            "horas_persona_faltantes": row["missing_person_hours"],
            "llegadas_tarde_estimadas": _value(
                row, "arrival", "late_arrivals_estimated"
            ),
            "promedio_tarde_min": _value(
                row, "arrival", "average_late_minutes"
            ),
            "salidas_anticipadas_estimadas": _value(
                row, "departure", "early_departures_estimated"
            ),
            "promedio_anticipacion_min": _value(
                row, "departure", "average_early_minutes"
            ),
            "salidas_despues_de_hora_estimadas": _value(
                row, "departure", "overtime_departures_estimated"
            ),
            "promedio_extra_min": _value(
                row, "departure", "average_overtime_minutes"
            ),
            "pausas_estimadas": _value(row, "meal", "breaks_estimated"),
            "pausas_excedidas_estimadas": _value(
                row, "meal", "overruns_estimated"
            ),
            "promedio_pausa_min": _value(
                row, "meal", "average_break_minutes"
            ),
        })
    filename = f"aeye-actividad-{report['date']}.csv"
    return Response(
        output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
