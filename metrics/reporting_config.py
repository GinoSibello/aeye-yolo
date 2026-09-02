"""Normaliza y persiste la configuracion de reportes anonimos."""

import json
from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo


ROLES = {"workstation", "restroom", "dining", "other"}
DEFAULT_ROI = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]


def _clock(value, field):
    """Valida un horario HH:MM y conserva ausencia explicita."""
    if value in (None, ""):
        return None
    text = str(value)
    try:
        hour, minute = (int(part) for part in text.split(":", 1))
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field} debe usar HH:MM") from error
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError(f"{field} esta fuera de rango")
    return f"{hour:02d}:{minute:02d}"


def _nonnegative(value, field, default):
    """Convierte una opcion numerica y rechaza tiempos negativos."""
    result = default if value is None else float(value)
    if result < 0:
        raise ValueError(f"{field} no puede ser negativo")
    return result


def _workdays(value):
    """Normaliza dias como enteros de lunes 0 a domingo 6."""
    days = [0, 1, 2, 3, 4] if value is None else list(value)
    if not days or any(isinstance(day, bool) or int(day) not in range(7) for day in days):
        raise ValueError("reporting.workdays debe contener dias entre 0 y 6")
    return sorted(set(int(day) for day in days))


def _points(value, field, minimum):
    """Valida coordenadas normalizadas sin asumir una resolucion de camara."""
    points = DEFAULT_ROI if value is None else value
    if not isinstance(points, list) or len(points) < minimum:
        raise ValueError(f"{field} requiere al menos {minimum} puntos")
    normalized = []
    for point in points:
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            raise ValueError(f"{field} contiene un punto invalido")
        x, y = (float(coordinate) for coordinate in point)
        if not 0.0 <= x <= 1.0 or not 0.0 <= y <= 1.0:
            raise ValueError(f"{field} debe usar coordenadas entre 0 y 1")
        normalized.append([x, y])
    return normalized


def normalize_reporting(config):
    """Devuelve opciones globales validas con horarios aun configurables."""
    source = deepcopy(config.get("reporting", {}))
    timezone = source.get("timezone", "America/Argentina/Buenos_Aires")
    try:
        ZoneInfo(timezone)
    except Exception as error:
        raise ValueError(f"Zona horaria invalida: {timezone}") from error
    shift = source.get("shift", {})
    meal = source.get("meal", {})
    return {
        "enabled": bool(source.get("enabled", True)),
        "timezone": timezone,
        "workdays": _workdays(source.get("workdays")),
        "shift_start": _clock(shift.get("start"), "reporting.shift.start"),
        "shift_end": _clock(shift.get("end"), "reporting.shift.end"),
        "arrival_grace_minutes": _nonnegative(
            shift.get("arrival_grace_minutes"), "arrival_grace_minutes", 5
        ),
        "early_departure_tolerance_minutes": _nonnegative(
            shift.get("early_departure_tolerance_minutes"),
            "early_departure_tolerance_minutes",
            5,
        ),
        "overtime_tolerance_minutes": _nonnegative(
            shift.get("overtime_tolerance_minutes"),
            "overtime_tolerance_minutes",
            10,
        ),
        "overtime_observation_minutes": _nonnegative(
            shift.get("overtime_observation_minutes"),
            "overtime_observation_minutes",
            180,
        ),
        "meal_window_start": _clock(
            meal.get("window_start"), "reporting.meal.window_start"
        ),
        "meal_window_end": _clock(
            meal.get("window_end"), "reporting.meal.window_end"
        ),
        "meal_allowed_minutes": (
            None
            if meal.get("allowed_minutes") in (None, "")
            else _nonnegative(
                meal.get("allowed_minutes"), "meal.allowed_minutes", 0
            )
        ),
        "max_sample_gap_seconds": max(
            1.0,
            _nonnegative(
                source.get("max_sample_gap_seconds"),
                "max_sample_gap_seconds",
                15,
            ),
        ),
        "absence_merge_gap_minutes": _nonnegative(
            source.get("absence_merge_gap_minutes"),
            "absence_merge_gap_minutes",
            2,
        ),
        "track_session_gap_seconds": max(
            1.0,
            _nonnegative(
                source.get("track_session_gap_seconds"),
                "track_session_gap_seconds",
                15,
            ),
        ),
    }


def camera_reporting(camera, global_settings):
    """Combina opciones globales con overrides y rol de una camara."""
    override = camera.get("reporting", {})
    role = camera.get("role", "workstation")
    if role not in ROLES:
        raise ValueError(f"Rol invalido en {camera['id']}: {role}")
    expected = camera.get("expected_people")
    if expected is None:
        minimum = camera.get("min_people")
        maximum = camera.get("max_people")
        if minimum is not None and maximum is not None and int(minimum) == int(maximum):
            expected = int(minimum)
    if expected is not None:
        if isinstance(expected, bool) or int(expected) < 0:
            raise ValueError(f"expected_people invalido en {camera['id']}")
        expected = int(expected)

    settings = dict(global_settings)
    shift = override.get("shift", {})
    meal = override.get("meal", {})
    for key, value in {
        "shift_start": _clock(shift.get("start"), f"{camera['id']}.shift.start"),
        "shift_end": _clock(shift.get("end"), f"{camera['id']}.shift.end"),
        "meal_window_start": _clock(
            meal.get("window_start"), f"{camera['id']}.meal.window_start"
        ),
        "meal_window_end": _clock(
            meal.get("window_end"), f"{camera['id']}.meal.window_end"
        ),
    }.items():
        if value is not None:
            settings[key] = value
    if "workdays" in override:
        settings["workdays"] = _workdays(override["workdays"])
    numeric = {
        "arrival_grace_minutes": shift,
        "early_departure_tolerance_minutes": shift,
        "overtime_tolerance_minutes": shift,
        "overtime_observation_minutes": shift,
    }
    for key, source in numeric.items():
        if key in source and source[key] is not None:
            settings[key] = _nonnegative(source[key], f"{camera['id']}.{key}", 0)

    if "allowed_minutes" in meal:
        settings["meal_allowed_minutes"] = (
            None
            if meal["allowed_minutes"] in (None, "")
            else _nonnegative(
                meal["allowed_minutes"],
                f"{camera['id']}.meal.allowed_minutes",
                0,
            )
        )
    roi = _points(camera.get("roi"), f"{camera['id']}.roi", 3)
    access = deepcopy(camera.get("access_line", {}))
    access["enabled"] = bool(access.get("enabled", False))
    if access["enabled"]:
        line = _points(
            [access.get("start"), access.get("end")],
            f"{camera['id']}.access_line",
            2,
        )
        if line[0] == line[1]:
            raise ValueError(f"Linea de acceso sin longitud en {camera['id']}")
        access["start"], access["end"] = line
        if access.get("inside_side", "left") not in {"left", "right"}:
            raise ValueError(f"inside_side invalido en {camera['id']}")
        access["inside_side"] = access.get("inside_side", "left")
        access["hysteresis"] = float(access.get("hysteresis", 0.015))

    reporting_enabled = bool(
        global_settings["enabled"]
        and camera.get(
            "reporting_enabled",
            camera.get("record_metrics", camera.get("monitor_staffing", False)),
        )
    )
    missing = []
    if role == "workstation":
        if expected is None:
            missing.append("expected_people")
        if not settings["shift_start"] or not settings["shift_end"]:
            missing.append("shift")
    if role in {"restroom", "dining"} and not access["enabled"]:
        missing.append("access_line")
    if role == "workstation" and (
        not settings["meal_window_start"]
        or not settings["meal_window_end"]
        or settings["meal_allowed_minutes"] is None
    ):
        missing.append("meal")
    if not reporting_enabled:
        status = "pending"
    elif not missing:
        status = "ready"
    elif role == "workstation" and (
        expected is None or not settings["shift_start"] or not settings["shift_end"]
    ):
        status = "pending"
    else:
        status = "partial"
    return {
        **settings,
        "camera_id": camera["id"],
        "display_name": camera.get("name", camera["id"]),
        "zone": camera.get("zone", ""),
        "role": role,
        "reporting_enabled": reporting_enabled,
        "expected_people": expected,
        "roi": roi,
        "access_line": access,
        "configuration_status": status,
        "missing_fields": missing,
    }


def prepare_cameras(config):
    """Aplica dotacion fija al monitor y habilita registro independiente."""
    global_settings = normalize_reporting(config)
    rows = []
    for camera in config.get("cameras", []):
        row = camera_reporting(camera, global_settings)
        camera["record_metrics"] = bool(row["reporting_enabled"])
        if row["role"] == "workstation" and row["expected_people"] is not None:
            camera["min_people"] = row["expected_people"]
            camera["max_people"] = row["expected_people"]
        rows.append(row)
    return rows


def sync_reporting_configuration(repository, config, at=None):
    """Materializa configuracion para que la API no dependa del proceso de vision."""
    now = at or datetime.now().astimezone()
    rows = prepare_cameras(config)
    for camera, row in zip(config.get("cameras", []), rows):
        repository.upsert_camera(camera, now)
        repository.upsert_workplace({
            **row,
            "workdays_json": json.dumps(row["workdays"]),
            "roi_json": json.dumps(row["roi"]),
            "access_line_json": json.dumps(row["access_line"]),
            "updated_at": now,
        })
    return rows
