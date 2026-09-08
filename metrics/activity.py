"""Calcula reportes diarios anonimos a partir de muestras auditables."""

import json
import math
import statistics
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


UTC = timezone.utc


def _round(value, digits=2):
    """Redondea valores presentes sin transformar ausencia en cero."""
    return round(value, digits) if isinstance(value, (int, float)) else None


def _ratio(numerator, denominator):
    """Devuelve porcentaje o ausencia cuando no existe denominador."""
    return 100.0 * numerator / denominator if denominator else None


def _percentile(values, percentile):
    """Interpola un percentil para listas pequenas sin numpy."""
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _timestamp(value):
    """Convierte timestamps SQLite a UTC consciente."""
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _clock(day, value, tz):
    """Combina fecha local y HH:MM."""
    hour, minute = (int(part) for part in value.split(":", 1))
    return datetime.combine(day, time(hour, minute), tzinfo=tz)


def _shift_period(day, settings, tz):
    """Construye un turno y admite salida al dia siguiente."""
    if not settings.get("shift_start") or not settings.get("shift_end"):
        return None
    start = _clock(day, settings["shift_start"], tz)
    end = _clock(day, settings["shift_end"], tz)
    if end <= start:
        end += timedelta(days=1)
    return start.astimezone(UTC), end.astimezone(UTC)


def _period_from_clocks(day, start_text, end_text, tz, anchor=None):
    """Resuelve una ventana local, incluso cuando cruza medianoche."""
    if not start_text or not end_text:
        return None
    start = _clock(day, start_text, tz)
    end = _clock(day, end_text, tz)
    if anchor and start < anchor.astimezone(tz) - timedelta(hours=12):
        start += timedelta(days=1)
        end += timedelta(days=1)
    if end <= start:
        end += timedelta(days=1)
    return start.astimezone(UTC), end.astimezone(UTC)


def build_intervals(rows, start, end, max_gap_seconds):
    """Convierte muestras puntuales en intervalos acotados y verificables."""
    ordered = sorted(rows, key=lambda row: row["sampled_at"])
    timestamps = [_timestamp(row["sampled_at"]) for row in ordered]
    intervals = []
    max_gap = timedelta(seconds=max_gap_seconds)
    for index, row in enumerate(ordered):
        sampled_at = timestamps[index]
        next_at = (
            timestamps[index + 1]
            if index + 1 < len(ordered)
            else sampled_at + max_gap
        )
        interval_start = max(start, sampled_at)
        interval_end = min(end, next_at, sampled_at + max_gap)
        if interval_end <= interval_start:
            continue
        valid = row["data_status"] == "valid" and row["people_count"] is not None
        count = int(row["people_count"]) if valid else None
        previous = intervals[-1] if intervals else None
        if (
            previous
            and previous["end"] == interval_start
            and previous["valid"] == valid
            and previous["count"] == count
        ):
            previous["end"] = interval_end
            previous["seconds"] = (
                previous["end"] - previous["start"]
            ).total_seconds()
            continue
        intervals.append({
            "start": interval_start,
            "end": interval_end,
            "seconds": (interval_end - interval_start).total_seconds(),
            "valid": valid,
            "count": count,
        })
    return intervals


def _clip(intervals, start, end):
    """Recorta intervalos conservando conteo y calidad."""
    clipped = []
    for interval in intervals:
        left = max(start, interval["start"])
        right = min(end, interval["end"])
        if right <= left:
            continue
        clipped.append({
            **interval,
            "start": left,
            "end": right,
            "seconds": (right - left).total_seconds(),
        })
    return clipped


def _aggregate(intervals, start, end, expected=None):
    """Integra ocupacion, faltantes y cobertura sobre un periodo."""
    selected = _clip(intervals, start, end)
    duration = max(0.0, (end - start).total_seconds())
    valid = [interval for interval in selected if interval["valid"]]
    valid_seconds = sum(interval["seconds"] for interval in valid)
    person_seconds = sum(
        interval["seconds"] * interval["count"] for interval in valid
    )
    result = {
        "period_seconds": duration,
        "valid_seconds": valid_seconds,
        "data_coverage_percent": _round(_ratio(valid_seconds, duration), 1),
        "average_occupancy": _round(
            person_seconds / valid_seconds if valid_seconds else None
        ),
        "person_hours": _round(person_seconds / 3600.0 if valid_seconds else None),
        "minimum_occupancy": min(
            (interval["count"] for interval in valid), default=None
        ),
        "maximum_occupancy": max(
            (interval["count"] for interval in valid), default=None
        ),
    }
    if expected is None:
        result.update({
            "complete_seconds": None,
            "staffing_coverage_percent": None,
            "understaffed_minutes": None,
            "missing_person_hours": None,
            "empty_minutes": _round(sum(
                interval["seconds"]
                for interval in valid
                if interval["count"] == 0
            ) / 60.0 if valid_seconds else None),
        })
        return result
    complete = sum(
        interval["seconds"] for interval in valid
        if interval["count"] >= expected
    )
    understaffed = sum(
        interval["seconds"] for interval in valid
        if interval["count"] < expected
    )
    missing_person_seconds = sum(
        interval["seconds"] * max(0, expected - interval["count"])
        for interval in valid
    )
    result.update({
        "complete_seconds": complete,
        "staffing_coverage_percent": _round(
            _ratio(complete, valid_seconds), 1
        ),
        "understaffed_minutes": _round(understaffed / 60.0 if valid_seconds else None),
        "missing_person_hours": _round(missing_person_seconds / 3600.0 if valid_seconds else None),
        "empty_minutes": _round(sum(
            interval["seconds"]
            for interval in valid
            if interval["count"] == 0
        ) / 60.0 if valid_seconds else None),
    })
    return result


def _window_coverage(intervals, start, end):
    """Mide si existe evidencia suficiente alrededor de un evento horario."""
    return _aggregate(intervals, start, end)["data_coverage_percent"] or 0.0


def _arrival_metrics(intervals, shift_start, shift_end, expected, grace_minutes):
    """Asigna la primera presencia de cada cupo sin identificar personas."""
    probe_end = min(shift_end, shift_start + timedelta(minutes=15))
    if _window_coverage(intervals, shift_start, probe_end) < 80.0:
        return {
            "status": "insufficient_data",
            "late_arrivals_estimated": None,
            "average_late_minutes": None,
            "absent_slots": None,
        }
    grace = shift_start + timedelta(minutes=grace_minutes)
    first_presence = []
    valid = [
        interval for interval in _clip(intervals, shift_start, shift_end)
        if interval["valid"]
    ]
    for slot in range(1, expected + 1):
        first = next(
            (
                interval["start"]
                for interval in valid
                if interval["count"] >= slot
            ),
            None,
        )
        first_presence.append(first)
    late_minutes = [
        (first - shift_start).total_seconds() / 60.0
        for first in first_presence
        if first is not None and first > grace
    ]
    return {
        "status": "estimated",
        "late_arrivals_estimated": len(late_minutes),
        "average_late_minutes": _round(
            statistics.fmean(late_minutes) if late_minutes else 0.0
        ),
        "maximum_late_minutes": _round(max(late_minutes, default=0.0)),
        "absent_slots": sum(first is None for first in first_presence),
    }


def _departure_metrics(
    intervals,
    shift_start,
    shift_end,
    expected,
    early_tolerance_minutes,
    overtime_tolerance_minutes,
    overtime_observation_minutes,
):
    """Estima ultima presencia de cada cupo antes y despues del turno."""
    probe_start = max(shift_start, shift_end - timedelta(minutes=15))
    end_coverage = _window_coverage(intervals, probe_start, shift_end)
    shift_valid = [
        interval for interval in _clip(intervals, shift_start, shift_end)
        if interval["valid"]
    ]
    early = []
    if end_coverage >= 80.0:
        cutoff = shift_end - timedelta(minutes=early_tolerance_minutes)
        for slot in range(1, expected + 1):
            present = [
                interval for interval in shift_valid
                if interval["count"] >= slot
            ]
            if present and present[-1]["end"] < cutoff:
                early.append(
                    (shift_end - present[-1]["end"]).total_seconds() / 60.0
                )

    overtime_start = shift_end + timedelta(minutes=overtime_tolerance_minutes)
    overtime_end = shift_end + timedelta(minutes=overtime_observation_minutes)
    overtime_probe_end = min(
        overtime_end, overtime_start + timedelta(minutes=15)
    )
    overtime_coverage = _window_coverage(
        intervals, overtime_start, overtime_probe_end
    )
    overtime = []
    if overtime_coverage >= 80.0:
        after = [
            interval for interval in _clip(
                intervals, overtime_start, overtime_end
            )
            if interval["valid"]
        ]
        for slot in range(1, expected + 1):
            present = [interval for interval in after if interval["count"] >= slot]
            if present:
                overtime.append(
                    (present[-1]["end"] - shift_end).total_seconds() / 60.0
                )
    return {
        "early_departures_status": (
            "estimated" if end_coverage >= 80.0 else "insufficient_data"
        ),
        "early_departures_estimated": (
            len(early) if end_coverage >= 80.0 else None
        ),
        "average_early_minutes": _round(
            statistics.fmean(early) if early else 0.0
        ) if end_coverage >= 80.0 else None,
        "overtime_status": (
            "estimated" if overtime_coverage >= 80.0 else "insufficient_data"
        ),
        "overtime_departures_estimated": (
            len(overtime) if overtime_coverage >= 80.0 else None
        ),
        "average_overtime_minutes": _round(
            statistics.fmean(overtime) if overtime else 0.0
        ) if overtime_coverage >= 80.0 else None,
        "maximum_overtime_minutes": _round(
            max(overtime, default=0.0)
        ) if overtime_coverage >= 80.0 else None,
    }


def _merge_ranges(ranges, gap):
    """Une ausencias cercanas para tolerar fluctuaciones breves."""
    merged = []
    for start, end in sorted(ranges):
        if merged and start - merged[-1][1] <= gap:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _meal_metrics(
    intervals,
    shift_start,
    shift_end,
    meal_start,
    meal_end,
    expected,
    allowed_minutes,
    merge_gap_minutes,
):
    """Estima pausas por cupo usando ausencias iniciadas en la ventana de comida."""
    if not meal_start or not meal_end or allowed_minutes is None:
        return {
            "status": "not_configured",
            "breaks_estimated": None,
            "overruns_estimated": None,
            "average_break_minutes": None,
        }
    if _window_coverage(intervals, meal_start, meal_end) < 80.0:
        return {
            "status": "insufficient_data",
            "breaks_estimated": None,
            "overruns_estimated": None,
            "average_break_minutes": None,
        }
    gap = timedelta(minutes=merge_gap_minutes)
    analysis = [
        interval for interval in _clip(intervals, shift_start, shift_end)
        if interval["valid"]
    ]
    durations = []
    for slot in range(1, expected + 1):
        presence_before = any(
            interval["count"] >= slot and interval["start"] < meal_start
            for interval in analysis
        )
        if not presence_before:
            continue
        absent = _merge_ranges(
            [
                (interval["start"], interval["end"])
                for interval in analysis
                if interval["count"] < slot
            ],
            gap,
        )
        for start, end in absent:
            if meal_start <= start < meal_end:
                durations.append((end - start).total_seconds() / 60.0)
    return {
        "status": "estimated",
        "breaks_estimated": len(durations),
        "overruns_estimated": sum(
            duration > allowed_minutes for duration in durations
        ),
        "average_break_minutes": _round(
            statistics.fmean(durations) if durations else 0.0
        ),
        "maximum_break_minutes": _round(max(durations, default=0.0)),
        "allowed_minutes": allowed_minutes,
    }


def _visible_sessions(rows, maximum_gap_seconds):
    """Agrupa tracks locales por ejecucion sin tratarlos como personas unicas."""
    grouped = {}
    for row in rows:
        grouped.setdefault(
            (row["run_id"], row["track_id"]), []
        ).append(_timestamp(row["sampled_at"]))
    durations = []
    gap = timedelta(seconds=maximum_gap_seconds)
    for timestamps in grouped.values():
        ordered = sorted(timestamps)
        started = previous = ordered[0]
        for current in ordered[1:]:
            if current - previous > gap:
                durations.append((previous - started).total_seconds())
                started = current
            previous = current
        durations.append((previous - started).total_seconds())
    return durations


def _setting(row):
    """Decodifica los campos JSON de una configuracion materializada."""
    result = dict(row)
    result["workdays"] = json.loads(result.pop("workdays_json"))
    result["roi"] = json.loads(result.pop("roi_json"))
    result["access_line"] = json.loads(result.pop("access_line_json"))
    result["reporting_enabled"] = bool(result["reporting_enabled"])
    return result


class ActivityAnalytics:
    """Construye reportes diarios por puesto y areas especiales."""

    def __init__(self, repository):
        self.repository = repository

    def configuration(self):
        """Expone configuracion efectiva sin secretos de conexion."""
        return [_setting(row) for row in self.repository.workplaces(False)]

    def _samples(self, camera_id, start, end):
        return self.repository.query(
            """SELECT sampled_at,people_count,raw_people_count,data_status,status
            FROM occupancy_samples WHERE camera_id=? AND sampled_at>=?
            AND sampled_at<? ORDER BY sampled_at""",
            (camera_id, start.isoformat(), end.isoformat()),
        )

    def _tracks(self, camera_id, start, end):
        return self.repository.query(
            """SELECT run_id,track_id,sampled_at
            FROM anonymous_track_observations WHERE camera_id=?
            AND sampled_at>=? AND sampled_at<? ORDER BY sampled_at""",
            (camera_id, start.isoformat(), end.isoformat()),
        )

    def _visits(self, camera_id, start, end):
        return self.repository.query(
            """SELECT entered_at,exited_at,duration_seconds,confidence,status
            FROM anonymous_visits WHERE camera_id=? AND entered_at>=?
            AND entered_at<? ORDER BY entered_at""",
            (camera_id, start.isoformat(), end.isoformat()),
        )

    def _access_counts(self, camera_id, start, end):
        rows = self.repository.query(
            """SELECT event_type,COUNT(*) count FROM access_events
            WHERE camera_id=? AND observed_at>=? AND observed_at<?
            GROUP BY event_type""",
            (camera_id, start.isoformat(), end.isoformat()),
        )
        counts = {"entry": 0, "exit": 0}
        counts.update({row["event_type"]: row["count"] for row in rows})
        return counts

    def _alerts(self, camera_id, start, end):
        """Cuenta alertas emitidas, distinguiendo faltantes y sobrantes."""
        rows = self.repository.query(
            """SELECT kind,COUNT(*) count FROM incidents
            WHERE camera_id=? AND alerted_at>=? AND alerted_at<?
            GROUP BY kind""",
            (camera_id, start.isoformat(), end.isoformat()),
        )
        counts = {"total": 0, "missing": 0, "extra": 0}
        for row in rows:
            counts[row["kind"]] = row["count"]
            counts["total"] += row["count"]
        return counts

    def _hourly(self, intervals, day, tz, expected):
        """Resume 24 bandas horarias para la visualizacion."""
        start = datetime.combine(day, time.min, tzinfo=tz).astimezone(UTC)
        end = (
            datetime.combine(day, time.min, tzinfo=tz)
            + timedelta(days=1)
        ).astimezone(UTC)
        return _hourly_profile(intervals, start, end, tz, expected)

    def _workstation(
        self,
        setting,
        day,
        tz,
        day_start,
        day_end,
        samples=None,
        intervals=None,
        alerts=None,
    ):
        """Calcula ocupacion y eventos estimados de un puesto."""
        expected = setting["expected_people"]
        shift = _shift_period(day, setting, tz)
        scheduled = day.weekday() in setting["workdays"] and shift is not None
        query_start = day_start
        query_end = day_end
        if shift:
            query_start = min(query_start, shift[0])
            query_end = max(
                query_end,
                shift[1] + timedelta(
                    minutes=setting["overtime_observation_minutes"]
                ),
            )
        if samples is None:
            samples = self._samples(setting["camera_id"], query_start, query_end)
        if intervals is None:
            intervals = build_intervals(
                samples,
                query_start,
                query_end,
                setting["max_sample_gap_seconds"],
            )
        else:
            intervals = _clip(intervals, query_start, query_end)
        report_start, report_end = shift if scheduled else (day_start, day_end)
        aggregate = _aggregate(
            intervals,
            report_start,
            report_end,
            expected if scheduled else None,
        )
        latest = next(
            (
                row["people_count"]
                for row in reversed(samples)
                if row["data_status"] == "valid"
            ),
            None,
        )
        row = {
            "camera_id": setting["camera_id"],
            "date": day.isoformat(),
            "name": setting["display_name"],
            "zone": setting["zone"],
            "role": setting["role"],
            "configuration_status": setting["configuration_status"],
            "expected_people": expected,
            "scheduled": scheduled,
            "shift_start": setting["shift_start"],
            "shift_end": setting["shift_end"],
            "arrival_grace_minutes": setting["arrival_grace_minutes"],
            "latest_occupancy": latest,
            **aggregate,
            "occupancy_percent": (
                _round(_ratio(aggregate["average_occupancy"], expected), 1)
                if (
                    scheduled
                    and expected
                    and aggregate["average_occupancy"] is not None
                ) else None
            ),
            "hourly": self._hourly(intervals, day, tz, expected),
            "alerts": (
                alerts if alerts is not None else self._alerts(
                    setting["camera_id"], day_start, day_end
                )
            ),
        }
        if not scheduled or expected is None:
            row.update({
                "arrival": {"status": "not_configured"},
                "departure": {
                    "early_departures_status": "not_configured",
                    "overtime_status": "not_configured",
                },
                "meal": {"status": "not_configured"},
            })
            return row

        row["arrival"] = _arrival_metrics(
            intervals,
            report_start,
            report_end,
            expected,
            setting["arrival_grace_minutes"],
        )
        row["departure"] = _departure_metrics(
            intervals,
            report_start,
            report_end,
            expected,
            setting["early_departure_tolerance_minutes"],
            setting["overtime_tolerance_minutes"],
            setting["overtime_observation_minutes"],
        )
        meal = _period_from_clocks(
            day,
            setting["meal_window_start"],
            setting["meal_window_end"],
            tz,
            report_start,
        )
        row["meal"] = _meal_metrics(
            intervals,
            report_start,
            report_end,
            meal[0] if meal else None,
            meal[1] if meal else None,
            expected,
            setting["meal_allowed_minutes"],
            setting["absence_merge_gap_minutes"],
        )
        return row

    def _special_area(self, setting, day_start, day_end):
        """Resume ocupacion, tracks visibles y cruces de un area especial."""
        samples = self._samples(setting["camera_id"], day_start, day_end)
        intervals = build_intervals(
            samples,
            day_start,
            day_end,
            setting["max_sample_gap_seconds"],
        )
        aggregate = _aggregate(intervals, day_start, day_end)
        tracks = self._tracks(setting["camera_id"], day_start, day_end)
        visible = _visible_sessions(
            tracks, setting["track_session_gap_seconds"]
        ) if tracks else []
        visits = [
            row for row in self._visits(
                setting["camera_id"], day_start, day_end
            )
            if row["status"] == "completed" and row["duration_seconds"] is not None
        ]
        durations = [row["duration_seconds"] / 60.0 for row in visits]
        allowed = setting["meal_allowed_minutes"] if setting["role"] == "dining" else None
        access = self._access_counts(
            setting["camera_id"], day_start, day_end
        )
        tz = ZoneInfo(setting["timezone"])
        return {
            "camera_id": setting["camera_id"],
            "name": setting["display_name"],
            "zone": setting["zone"],
            "role": setting["role"],
            "configuration_status": setting["configuration_status"],
            **aggregate,
            "anonymous_tracks_seen": len({
                (row["run_id"], row["track_id"]) for row in tracks
            }),
            "visible_sessions": len(visible),
            "average_visible_minutes": _round(
                statistics.fmean(visible) / 60.0 if visible else None
            ),
            "entries": access["entry"],
            "exits": access["exit"],
            "completed_visits": len(visits),
            "average_visit_minutes": _round(
                statistics.fmean(durations) if durations else None
            ),
            "p95_visit_minutes": _round(_percentile(durations, 0.95)),
            "visits_over_allowed": (
                sum(duration > allowed for duration in durations)
                if allowed is not None
                else None
            ),
            "visit_measurement": (
                "fifo_estimate"
                if setting["access_line"].get("enabled")
                else "access_line_pending"
            ),
            "hourly": _hourly_profile(
                intervals, day_start, day_end, tz
            ),
            "alerts": self._alerts(
                setting["camera_id"], day_start, day_end
            ),
        }

    def daily_report(self, selected_day, include_special_areas=True):
        """Genera el reporte consolidado para una fecha local."""
        if isinstance(selected_day, str):
            selected_day = date.fromisoformat(selected_day)
        settings = [
            _setting(row) for row in self.repository.workplaces()
        ]
        timezone_name = (
            settings[0]["timezone"]
            if settings
            else "America/Argentina/Buenos_Aires"
        )
        tz = ZoneInfo(timezone_name)
        local_start = datetime.combine(selected_day, time.min, tzinfo=tz)
        local_end = local_start + timedelta(days=1)
        day_start = local_start.astimezone(UTC)
        day_end = local_end.astimezone(UTC)

        workstations = []
        special_areas = []
        for setting in settings:
            if setting["role"] == "workstation":
                workstations.append(self._workstation(
                    setting, selected_day, tz, day_start, day_end
                ))
            elif (
                include_special_areas
                and setting["role"] in {"restroom", "dining"}
            ):
                special_areas.append(self._special_area(
                    setting, day_start, day_end
                ))

        scheduled = [row for row in workstations if row["scheduled"]]
        valid_seconds = sum(row["valid_seconds"] for row in scheduled)
        period_seconds = sum(row["period_seconds"] for row in scheduled)
        staffing_ready = bool(scheduled) and all(
            row["expected_people"] is not None for row in scheduled
        )
        complete_seconds = sum(
            row["complete_seconds"] or 0 for row in scheduled
        )
        arrivals_ready = bool(scheduled) and all(
            row["arrival"].get("status") == "estimated"
            for row in scheduled
        )
        departures_ready = bool(scheduled) and all(
            row["departure"].get("early_departures_status") == "estimated"
            for row in scheduled
        )
        overtime_ready = bool(scheduled) and all(
            row["departure"].get("overtime_status") == "estimated"
            for row in scheduled
        )
        meals_ready = bool(scheduled) and all(
            row["meal"].get("status") == "estimated"
            for row in scheduled
        )
        late_count = (
            sum(
                row["arrival"].get("late_arrivals_estimated") or 0
                for row in scheduled
            )
            if arrivals_ready else None
        )
        late_minutes_total = sum(
            (row["arrival"].get("average_late_minutes") or 0)
            * (row["arrival"].get("late_arrivals_estimated") or 0)
            for row in scheduled
        )
        alerts = {
            key: sum(row["alerts"][key] for row in workstations + special_areas)
            for key in ("total", "missing", "extra")
        }
        summary = {
            "workstations": len(workstations),
            "configured_workstations": sum(
                row["configuration_status"] == "ready"
                for row in workstations
            ),
            "pending_configuration": sum(
                row["configuration_status"] != "ready"
                for row in workstations + special_areas
            ),
            "expected_people": (
                sum(row["expected_people"] for row in scheduled)
                if staffing_ready else None
            ),
            "data_coverage_percent": _round(
                _ratio(valid_seconds, period_seconds), 1
            ),
            "staffing_coverage_percent": (
                _round(_ratio(complete_seconds, valid_seconds), 1)
                if staffing_ready else None
            ),
            "person_hours": (
                _round(sum(row["person_hours"] or 0 for row in scheduled))
                if valid_seconds else None
            ),
            "missing_person_hours": (
                _round(sum(
                    row["missing_person_hours"] or 0 for row in scheduled
                ))
                if staffing_ready and valid_seconds else None
            ),
            "late_arrivals_estimated": late_count,
            "average_late_minutes": (
                _round(
                    late_minutes_total / late_count if late_count else 0.0
                )
                if arrivals_ready else None
            ),
            "early_departures_estimated": (
                sum(
                    row["departure"].get("early_departures_estimated") or 0
                    for row in scheduled
                )
                if departures_ready else None
            ),
            "overtime_departures_estimated": (
                sum(
                    row["departure"].get("overtime_departures_estimated") or 0
                    for row in scheduled
                )
                if overtime_ready else None
            ),
            "meal_overruns_estimated": (
                sum(
                    row["meal"].get("overruns_estimated") or 0
                    for row in scheduled
                )
                if meals_ready else None
            ),
            "alerts_total": alerts["total"],
            "missing_alerts": alerts["missing"],
            "extra_alerts": alerts["extra"],
        }
        return {
            "schema_version": 1,
            "date": selected_day.isoformat(),
            "timezone": timezone_name,
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "interpretation": (
                "Aggregate anonymous estimates; no employee identification "
                "or cross-camera attribution"
            ),
            "summary": summary,
            "workstations": workstations,
            "special_areas": special_areas,
        }


def _hourly_profile(intervals, start, end, tz, expected=None):
    """Agrupa un rango por hora local en una sola pasada por intervalo."""
    totals = [{
        "period": 0.0,
        "valid": 0.0,
        "person": 0.0,
        "complete": 0.0,
    } for _ in range(24)]

    first_day = start.astimezone(tz).date()
    last_day = (end - timedelta(microseconds=1)).astimezone(tz).date()
    current_day = first_day
    while current_day <= last_day:
        for hour in range(24):
            local_start = datetime.combine(
                current_day, time(hour), tzinfo=tz
            )
            bucket_start = max(start, local_start.astimezone(UTC))
            bucket_end = min(
                end, (local_start + timedelta(hours=1)).astimezone(UTC)
            )
            if bucket_end > bucket_start:
                totals[hour]["period"] += (
                    bucket_end - bucket_start
                ).total_seconds()
        current_day += timedelta(days=1)

    for interval in _clip(intervals, start, end):
        cursor = interval["start"]
        while cursor < interval["end"]:
            local = cursor.astimezone(tz)
            next_hour = (
                local.replace(minute=0, second=0, microsecond=0)
                + timedelta(hours=1)
            ).astimezone(UTC)
            segment_end = min(interval["end"], next_hour)
            seconds = (segment_end - cursor).total_seconds()
            bucket = totals[local.hour]
            if interval["valid"]:
                bucket["valid"] += seconds
                bucket["person"] += seconds * interval["count"]
                if expected is not None and interval["count"] >= expected:
                    bucket["complete"] += seconds
            cursor = segment_end

    rows = []
    for hour, bucket in enumerate(totals):
        average = (
            bucket["person"] / bucket["valid"]
            if bucket["valid"] else None
        )
        rows.append({
            "hour": f"{hour:02d}:00",
            "average_occupancy": _round(average),
            "occupancy_percent": (
                _round(_ratio(average, expected), 1)
                if average is not None and expected else None
            ),
            "data_coverage_percent": _round(
                _ratio(bucket["valid"], bucket["period"]), 1
            ),
            "staffing_coverage_percent": (
                _round(_ratio(bucket["complete"], bucket["valid"]), 1)
                if expected is not None and bucket["valid"] else None
            ),
            "sample_weight_hours": _round(bucket["valid"] / 3600.0),
        })
    return rows
