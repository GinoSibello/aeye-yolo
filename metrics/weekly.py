"""Consolida reportes diarios en una vista semanal auditable."""

from bisect import bisect_left, bisect_right
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from metrics.activity import (
    ActivityAnalytics,
    UTC,
    build_intervals,
    _ratio,
    _round,
    _setting,
    _shift_period,
    _timestamp,
)


def _percentage(numerator, denominator):
    """Calcula un porcentaje redondeado preservando denominadores ausentes."""
    return _round(_ratio(numerator, denominator), 1)


def _weighted_average(rows, value_key, weight_key):
    """Promedia valores usando el peso verificable de cada fila."""
    pairs = [
        (row.get(value_key), row.get(weight_key) or 0)
        for row in rows
        if row.get(value_key) is not None and (row.get(weight_key) or 0) > 0
    ]
    denominator = sum(weight for _, weight in pairs)
    if not denominator:
        return None
    return _round(
        sum(value * weight for value, weight in pairs) / denominator
    )


def _measurement_status(measured, expected):
    """Distingue una medicion completa, parcial, ausente o no configurada."""
    if not expected:
        return "not_configured"
    if not measured:
        return "insufficient_data"
    return "estimated" if measured == expected else "partial"


def _event_average(rows, count_key, average_key):
    """Suma eventos y pondera su duracion por cantidad de eventos."""
    total = sum(row.get(count_key) or 0 for row in rows)
    if not rows:
        return None, None
    if not total:
        return 0, 0.0
    minutes = sum(
        (row.get(average_key) or 0) * (row.get(count_key) or 0)
        for row in rows
    )
    return total, _round(minutes / total)


def _nested_sum(rows, path):
    """Suma una metrica anidada solamente cuando hay valores disponibles."""
    values = []
    for row in rows:
        current = row
        for key in path:
            current = current.get(key) if isinstance(current, dict) else None
        if current is not None:
            values.append(current)
    return sum(values) if values else None


def _alert_summary(rows):
    """Suma solamente alertas que efectivamente fueron emitidas."""
    return {
        key: sum(row.get("alerts", {}).get(key, 0) for row in rows)
        for key in ("total", "missing", "extra")
    }


def _daily_breakdown(rows):
    """Conserva evidencia diaria para graficos de una camara."""
    result = []
    for row in rows:
        arrival = row.get("arrival", {})
        departure = row.get("departure", {})
        meal = row.get("meal", {})
        result.append({
            "date": row["date"],
            "scheduled": row["scheduled"],
            "occupancy_percent": row.get("occupancy_percent"),
            "data_coverage_percent": row.get("data_coverage_percent"),
            "late_arrivals_estimated": (
                arrival.get("late_arrivals_estimated")
                if arrival.get("status") == "estimated" else None
            ),
            "early_departures_estimated": (
                departure.get("early_departures_estimated")
                if departure.get("early_departures_status") == "estimated"
                else None
            ),
            "overtime_departures_estimated": (
                departure.get("overtime_departures_estimated")
                if departure.get("overtime_status") == "estimated" else None
            ),
            "meal_overruns_estimated": (
                meal.get("overruns_estimated")
                if meal.get("status") == "estimated" else None
            ),
            "alerts_total": row.get("alerts", {}).get("total", 0),
        })
    return result


class WeeklyActivityAnalytics:
    """Construye una semana de lunes a domingo desde reportes diarios."""

    def __init__(self, repository):
        self.repository = repository
        self.daily = ActivityAnalytics(repository)

    def _workstation(self, setting, rows):
        """Agrega ocupacion, eventos y perfiles horarios de un puesto."""
        scheduled = [row for row in rows if row["scheduled"]]
        measured_rows = scheduled or rows
        period_basis = "scheduled_shift" if scheduled else "calendar_day"
        valid_seconds = sum(row["valid_seconds"] for row in measured_rows)
        period_seconds = sum(row["period_seconds"] for row in measured_rows)
        person_seconds = sum(
            (row["person_hours"] or 0) * 3600 for row in measured_rows
        )
        expected = setting["expected_people"]
        expected_person_seconds = (
            valid_seconds * expected
            if expected is not None and valid_seconds else 0
        )

        hourly = []
        for hour_index in range(24):
            hour_rows = [row["hourly"][hour_index] for row in measured_rows]
            weighted_rows = [{
                **hour,
                "weight": (hour["data_coverage_percent"] or 0) / 100.0,
            } for hour in hour_rows]
            weight = sum(row["weight"] for row in weighted_rows)
            average = _weighted_average(
                weighted_rows, "average_occupancy", "weight"
            )
            hourly.append({
                "hour": f"{hour_index:02d}:00",
                "average_occupancy": average,
                "occupancy_percent": (
                    _percentage(average, expected)
                    if average is not None and expected else None
                ),
                "data_coverage_percent": _percentage(
                    weight, len(measured_rows)
                ),
                "sample_weight_hours": _round(weight),
            })

        arrival_rows = [
            row["arrival"] for row in scheduled
            if row["arrival"].get("status") == "estimated"
        ]
        late_count, average_late = _event_average(
            arrival_rows,
            "late_arrivals_estimated",
            "average_late_minutes",
        )
        meal_rows = [
            row["meal"] for row in scheduled
            if row["meal"].get("status") == "estimated"
        ]
        breaks, average_break = _event_average(
            meal_rows, "breaks_estimated", "average_break_minutes"
        )
        early_rows = [
            row["departure"] for row in scheduled
            if row["departure"].get("early_departures_status") == "estimated"
        ]
        early_count, average_early = _event_average(
            early_rows,
            "early_departures_estimated",
            "average_early_minutes",
        )
        overtime_rows = [
            row["departure"] for row in scheduled
            if row["departure"].get("overtime_status") == "estimated"
        ]
        overtime_count, average_overtime = _event_average(
            overtime_rows,
            "overtime_departures_estimated",
            "average_overtime_minutes",
        )

        missing_values = [
            row["missing_person_hours"] for row in scheduled
            if row["missing_person_hours"] is not None
        ]
        complete_rows = [
            row for row in scheduled
            if row["staffing_coverage_percent"] is not None
        ]
        complete_seconds = sum(
            row["complete_seconds"] or 0 for row in complete_rows
        )
        complete_valid_seconds = sum(
            row["valid_seconds"] for row in complete_rows
        )
        return {
            "camera_id": setting["camera_id"],
            "name": setting["display_name"],
            "zone": setting["zone"],
            "role": "workstation",
            "configuration_status": setting["configuration_status"],
            "expected_people": expected,
            "shift_start": setting["shift_start"],
            "shift_end": setting["shift_end"],
            "shifts": setting["shifts"],
            "arrival_grace_minutes": setting["arrival_grace_minutes"],
            "period_basis": period_basis,
            "scheduled_days": len(scheduled),
            "measured_days": sum(
                row["valid_seconds"] > 0 for row in measured_rows
            ),
            "period_seconds": period_seconds,
            "valid_seconds": valid_seconds,
            "data_coverage_percent": _percentage(
                valid_seconds, period_seconds
            ),
            "average_occupancy": _round(
                person_seconds / valid_seconds if valid_seconds else None
            ),
            "occupancy_percent": (
                _percentage(person_seconds, expected_person_seconds)
                if expected_person_seconds else None
            ),
            "staffing_coverage_percent": (
                _percentage(complete_seconds, complete_valid_seconds)
                if complete_valid_seconds else None
            ),
            "person_hours": _round(
                person_seconds / 3600.0 if valid_seconds else None
            ),
            "missing_person_hours": (
                _round(sum(missing_values)) if missing_values else None
            ),
            "arrival": {
                "status": _measurement_status(
                    len(arrival_rows), len(scheduled)
                ),
                "measured_days": len(arrival_rows),
                "late_arrivals_estimated": late_count,
                "average_late_minutes": average_late,
            },
            "departure": {
                "early_status": _measurement_status(
                    len(early_rows), len(scheduled)
                ),
                "early_measured_days": len(early_rows),
                "early_departures_estimated": early_count,
                "average_early_minutes": average_early,
                "overtime_status": _measurement_status(
                    len(overtime_rows), len(scheduled)
                ),
                "overtime_measured_days": len(overtime_rows),
                "overtime_departures_estimated": overtime_count,
                "average_overtime_minutes": average_overtime,
            },
            "meal": {
                "status": _measurement_status(
                    len(meal_rows), len(scheduled)
                ),
                "measured_days": len(meal_rows),
                "breaks_estimated": breaks,
                "overruns_estimated": (
                    sum(
                        row.get("overruns_estimated") or 0
                        for row in meal_rows
                    )
                    if meal_rows else None
                ),
                "average_break_minutes": average_break,
            },
            "hourly": hourly,
            "daily": _daily_breakdown(rows),
            "alerts": _alert_summary(rows),
        }

    def _daily_trend(self, reports):
        """Resume ocupacion y cobertura para cada dia de la semana."""
        daily = []
        for report in reports:
            scheduled = [
                row for row in report["workstations"] if row["scheduled"]
            ]
            rows = scheduled or report["workstations"]
            eligible = [
                row for row in rows
                if row["expected_people"] is not None
                and row["valid_seconds"] > 0
            ]
            person_seconds = sum(
                (row["person_hours"] or 0) * 3600 for row in eligible
            )
            expected_seconds = sum(
                row["valid_seconds"] * row["expected_people"]
                for row in eligible
            )
            daily.append({
                "date": report["date"],
                "occupancy_percent": (
                    _percentage(person_seconds, expected_seconds)
                    if expected_seconds else None
                ),
                "data_coverage_percent": _percentage(
                    sum(row["valid_seconds"] for row in rows),
                    sum(row["period_seconds"] for row in rows),
                ),
            })
        return daily

    def _hourly_summary(self, workstations):
        """Pondera el perfil horario por dotacion y horas con datos."""
        hourly = []
        for hour_index in range(24):
            rows = [
                (row, row["hourly"][hour_index])
                for row in workstations
                if row["expected_people"]
                and row["hourly"][hour_index]["average_occupancy"] is not None
            ]
            person_weight = sum(
                hour["average_occupancy"] * hour["sample_weight_hours"]
                for _, hour in rows
            )
            expected_weight = sum(
                row["expected_people"] * hour["sample_weight_hours"]
                for row, hour in rows
            )
            hourly.append({
                "hour": f"{hour_index:02d}:00",
                "occupancy_percent": (
                    _percentage(person_weight, expected_weight)
                    if expected_weight else None
                ),
                "data_weight_hours": _round(sum(
                    hour["sample_weight_hours"] for _, hour in rows
                )),
            })
        return hourly

    def _summary(self, workstations):
        """Calcula indicadores generales sin promediar porcentajes simples."""
        valid_seconds = sum(row["valid_seconds"] for row in workstations)
        period_seconds = sum(row["period_seconds"] for row in workstations)
        person_seconds = sum(
            (row["person_hours"] or 0) * 3600 for row in workstations
        )
        expected_seconds = sum(
            row["valid_seconds"] * row["expected_people"]
            for row in workstations
            if row["expected_people"] is not None
        )
        configured_person_seconds = sum(
            (row["person_hours"] or 0) * 3600
            for row in workstations
            if row["expected_people"] is not None
        )
        staffing_rows = [
            row for row in workstations
            if row["staffing_coverage_percent"] is not None
        ]

        late_count = _nested_sum(
            workstations, ("arrival", "late_arrivals_estimated")
        )
        average_late = None
        if late_count is not None:
            average_late = _round(
                sum(
                    (row["arrival"]["average_late_minutes"] or 0)
                    * (row["arrival"]["late_arrivals_estimated"] or 0)
                    for row in workstations
                    if row["arrival"]["late_arrivals_estimated"] is not None
                ) / late_count if late_count else 0.0
            )

        breaks = _nested_sum(workstations, ("meal", "breaks_estimated"))
        average_break = None
        if breaks is not None:
            average_break = _round(
                sum(
                    (row["meal"]["average_break_minutes"] or 0)
                    * (row["meal"]["breaks_estimated"] or 0)
                    for row in workstations
                    if row["meal"]["breaks_estimated"] is not None
                ) / breaks if breaks else 0.0
            )

        return {
            "workstations": len(workstations),
            "configured_workstations": sum(
                row["configuration_status"] == "ready"
                for row in workstations
            ),
            "expected_people": (
                sum(row["expected_people"] for row in workstations)
                if workstations and all(
                    row["expected_people"] is not None
                    for row in workstations
                ) else None
            ),
            "data_coverage_percent": _percentage(
                valid_seconds, period_seconds
            ),
            "average_occupancy": _round(
                person_seconds / valid_seconds if valid_seconds else None
            ),
            "occupancy_percent": (
                _percentage(configured_person_seconds, expected_seconds)
                if expected_seconds else None
            ),
            "staffing_coverage_percent": _weighted_average(
                staffing_rows, "staffing_coverage_percent", "valid_seconds"
            ),
            "person_hours": _round(
                person_seconds / 3600.0 if valid_seconds else None
            ),
            "missing_person_hours": _nested_sum(
                workstations, ("missing_person_hours",)
            ),
            "late_arrivals_estimated": late_count,
            "average_late_minutes": average_late,
            "early_departures_estimated": _nested_sum(
                workstations,
                ("departure", "early_departures_estimated"),
            ),
            "overtime_departures_estimated": _nested_sum(
                workstations,
                ("departure", "overtime_departures_estimated"),
            ),
            "meal_breaks_estimated": breaks,
            "meal_overruns_estimated": _nested_sum(
                workstations, ("meal", "overruns_estimated")
            ),
            "average_break_minutes": average_break,
            "scheduled_station_days": sum(
                row["scheduled_days"] for row in workstations
            ),
            "measured_station_days": sum(
                row["measured_days"] for row in workstations
            ),
            "hourly": self._hourly_summary(workstations),
        }

    def _period_report(self, period_start, period_end, period_name):
        """Consolida un rango cargando cada cámara una sola vez."""
        day_count = (period_end - period_start).days + 1
        days = [
            period_start + timedelta(days=offset)
            for offset in range(day_count)
        ]
        settings = [
            _setting(row) for row in self.repository.workplaces()
        ]
        timezone_name = (
            settings[0]["timezone"]
            if settings else "America/Argentina/Buenos_Aires"
        )
        tz = ZoneInfo(timezone_name)
        local_start = datetime.combine(period_start, time.min, tzinfo=tz)
        local_end = datetime.combine(
            period_end + timedelta(days=1), time.min, tzinfo=tz
        )
        start = local_start.astimezone(UTC)
        end = local_end.astimezone(UTC)

        daily_workstations = {day: [] for day in days}
        workstations = []
        for setting in settings:
            if setting["role"] != "workstation":
                continue
            sample_end = end + timedelta(days=1)
            all_samples = self.daily._samples(
                setting["camera_id"], start, sample_end
            )
            sample_times = [
                _timestamp(row["sampled_at"]) for row in all_samples
            ]
            all_intervals = build_intervals(
                all_samples,
                start,
                sample_end,
                setting["max_sample_gap_seconds"],
            )
            interval_starts = [row["start"] for row in all_intervals]
            interval_ends = [row["end"] for row in all_intervals]
            alert_rows = self.repository.query(
                """SELECT alerted_at,kind FROM incidents
                WHERE camera_id=? AND alerted_at>=? AND alerted_at<?
                ORDER BY alerted_at""",
                (
                    setting["camera_id"],
                    start.isoformat(),
                    end.isoformat(),
                ),
            )
            alerts_by_day = {
                day: {"total": 0, "missing": 0, "extra": 0}
                for day in days
            }
            for alert in alert_rows:
                alert_day = _timestamp(
                    alert["alerted_at"]
                ).astimezone(tz).date()
                if alert_day in alerts_by_day:
                    alerts_by_day[alert_day][alert["kind"]] += 1
                    alerts_by_day[alert_day]["total"] += 1
            camera_rows = []
            for day in days:
                day_start = datetime.combine(
                    day, time.min, tzinfo=tz
                ).astimezone(UTC)
                day_end = (
                    datetime.combine(day, time.min, tzinfo=tz)
                    + timedelta(days=1)
                ).astimezone(UTC)
                shift = _shift_period(day, setting, tz)
                query_start = min(day_start, shift[0]) if shift else day_start
                query_end = day_end
                if shift:
                    query_end = max(
                        day_end,
                        shift[1] + timedelta(
                            minutes=setting[
                                "overtime_observation_minutes"
                            ]
                        ),
                    )
                left = bisect_left(sample_times, query_start)
                right = bisect_left(sample_times, query_end)
                interval_left = bisect_right(interval_ends, query_start)
                interval_right = bisect_left(interval_starts, query_end)
                row = self.daily._workstation(
                    setting,
                    day,
                    tz,
                    day_start,
                    day_end,
                    samples=all_samples[left:right],
                    intervals=all_intervals[interval_left:interval_right],
                    alerts=alerts_by_day[day],
                )
                camera_rows.append(row)
                daily_workstations[day].append(row)
            workstations.append(self._workstation(setting, camera_rows))

        reports = [
            {
                "date": day.isoformat(),
                "workstations": daily_workstations[day],
            }
            for day in days
        ]
        special_areas = [
            self.daily._special_area(setting, start, end)
            for setting in settings
            if setting["role"] in {"restroom", "dining"}
        ]
        alerts = _alert_summary(workstations + special_areas)
        summary = self._summary(workstations)
        summary.update({
            "alerts_total": alerts["total"],
            "missing_alerts": alerts["missing"],
            "extra_alerts": alerts["extra"],
        })

        result = {
            "schema_version": 2,
            "period": period_name,
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "timezone": timezone_name,
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "interpretation": (
                "Aggregate anonymous estimates; no employee identification "
                "or cross-camera attribution"
            ),
            "limitations": {
                "restroom_by_workstation": "not_attributable",
                "employee_identity": "not_available",
            },
            "summary": summary,
            "daily": self._daily_trend(reports),
            "workstations": workstations,
            "special_areas": special_areas,
        }
        if period_name == "weekly":
            result["week_start"] = period_start.isoformat()
            result["week_end"] = period_end.isoformat()
        else:
            result["month_start"] = period_start.isoformat()
            result["month_end"] = period_end.isoformat()
        return result

    def weekly_report(self, selected_day):
        """Genera el reporte consolidado desde el lunes elegido."""
        if isinstance(selected_day, str):
            selected_day = date.fromisoformat(selected_day)
        week_start = selected_day - timedelta(days=selected_day.weekday())
        return self._period_report(
            week_start, week_start + timedelta(days=6), "weekly"
        )

    def monthly_report(self, selected_day):
        """Genera el reporte consolidado para el mes de la fecha elegida."""
        if isinstance(selected_day, str):
            selected_day = date.fromisoformat(selected_day)
        month_start = selected_day.replace(day=1)
        if month_start.month == 12:
            next_month = date(month_start.year + 1, 1, 1)
        else:
            next_month = date(
                month_start.year, month_start.month + 1, 1
            )
        return self._period_report(
            month_start, next_month - timedelta(days=1), "monthly"
        )
