"""Expone consultas analiticas de AEYE mediante FastAPI."""

import os
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, Query

from database.repository import Repository
from metrics.analytics import Analytics

repository = Repository(
    os.environ.get("AEYE_DB_PATH", "/workspace/aeye-yolo/data/aeye.db")
)
analytics = Analytics(repository)
app = FastAPI(title="AEYE API", version="0.1.0")


def period(start, end):
    """Valida un intervalo temporal y devuelve extremos ISO 8601."""
    if end <= start:
        raise HTTPException(422, "end debe ser posterior a start")
    return start.isoformat(), end.isoformat()


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
