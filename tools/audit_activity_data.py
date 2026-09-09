#!/usr/bin/env python3
"""Audita cobertura por turno y etiquetas visuales sin modificar SQLite."""

import argparse
import csv
import json
import sqlite3
import sys
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from metrics.activity import (
    ActivityAnalytics,
    _aggregate,
    _period_status,
    _setting,
    _shift_periods,
    build_intervals,
)


UTC = timezone.utc


class ReadOnlyRepository:
    """Adaptador minimo que impide migraciones y escrituras."""

    def __init__(self, path):
        resolved = Path(path).resolve()
        self.connection = sqlite3.connect(
            resolved.as_uri() + "?mode=ro", uri=True
        )
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA query_only = ON")

    def close(self):
        self.connection.close()

    def query(self, sql, params=()):
        return [
            dict(row)
            for row in self.connection.execute(sql, params).fetchall()
        ]

    def workplaces(self, enabled_only=True):
        where = "WHERE reporting_enabled=1" if enabled_only else ""
        return self.query(
            f"""SELECT * FROM workplace_settings {where}
            ORDER BY CASE role WHEN 'workstation' THEN 0
            WHEN 'restroom' THEN 1 WHEN 'dining' THEN 2 ELSE 3 END,
            display_name COLLATE NOCASE, camera_id"""
        )


def _number(value, field, row_number):
    try:
        return int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(
            f"Fila {row_number}: {field} debe ser un entero"
        ) from error


def load_visual_labels(path):
    """Agrupa conteos humanos locales por camara y turno."""
    grouped = defaultdict(list)
    if path is None:
        return grouped
    required = {
        "camera_id",
        "shift_id",
        "observed_at",
        "reported_count",
        "manual_count",
    }
    with Path(path).open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        missing = required - set(reader.fieldnames or ())
        if missing:
            raise ValueError(
                "Faltan columnas visuales: " + ", ".join(sorted(missing))
            )
        for row_number, row in enumerate(reader, start=2):
            reported = _number(
                row["reported_count"], "reported_count", row_number
            )
            manual = _number(
                row["manual_count"], "manual_count", row_number
            )
            grouped[(row["camera_id"], row["shift_id"])].append(
                {
                    "observed_at": row["observed_at"],
                    "reported": reported,
                    "manual": manual,
                }
            )
    return grouped


def summarize_visual(samples, minimum_samples, exact_threshold):
    """Calcula exactitud, error absoluto y direccion del sesgo."""
    count = len(samples)
    if not samples:
        return {
            "status": "pending",
            "sample_count": 0,
            "exact_percent": None,
            "mae": None,
            "signed_bias": None,
            "overcounts": None,
            "undercounts": None,
        }
    differences = [
        sample["reported"] - sample["manual"] for sample in samples
    ]
    exact = sum(difference == 0 for difference in differences)
    exact_percent = round(100.0 * exact / count, 1)
    if count < minimum_samples:
        status = "insufficient_samples"
    elif exact_percent >= exact_threshold:
        status = "passed"
    else:
        status = "failed"
    return {
        "status": status,
        "sample_count": count,
        "exact_percent": exact_percent,
        "mae": round(
            sum(abs(difference) for difference in differences) / count, 3
        ),
        "signed_bias": round(sum(differences) / count, 3),
        "overcounts": sum(difference > 0 for difference in differences),
        "undercounts": sum(difference < 0 for difference in differences),
    }


def _special_area_shifts(analytics, setting, selected_day, as_of):
    """Calcula cobertura por turno sin atribuir dotacion a areas anonimas."""
    tz = ZoneInfo(setting["timezone"])
    rows = []
    for period in _shift_periods(selected_day, setting, tz):
        effective_end = min(
            period["end_at"], max(period["start_at"], as_of)
        )
        samples = analytics._samples(
            setting["camera_id"], period["start_at"], effective_end
        )
        intervals = build_intervals(
            samples,
            period["start_at"],
            effective_end,
            setting["max_sample_gap_seconds"],
        )
        rows.append({
            "id": period["id"],
            "name": period["name"],
            "period_status": _period_status(
                period["start_at"], period["end_at"], as_of
            ),
            **_aggregate(
                intervals, period["start_at"], effective_end
            ),
        })
    return rows


def audit(args):
    selected_day = date.fromisoformat(args.day)
    labels = load_visual_labels(args.visual_labels)
    repository = ReadOnlyRepository(args.database)
    try:
        as_of = datetime.now(UTC)
        integrity = repository.connection.execute(
            "PRAGMA quick_check"
        ).fetchone()[0]
        analytics = ActivityAnalytics(repository)
        report = analytics.daily_report(
            selected_day, include_special_areas=False, as_of=as_of
        )
        settings = [_setting(row) for row in repository.workplaces()]
        special_shifts = {
            setting["camera_id"]: _special_area_shifts(
                analytics, setting, selected_day, as_of
            )
            for setting in settings
            if setting["role"] in {"restroom", "dining"}
        }
    finally:
        repository.close()

    configuration_verified = (
        args.configuration_valid_from is None
        or selected_day >= args.configuration_valid_from
    )
    rows = []
    cameras = [
        {
            "camera_id": workstation["camera_id"],
            "name": workstation["name"],
            "role": workstation["role"],
            "shifts": workstation.get("shifts", []),
        }
        for workstation in report["workstations"]
    ]
    cameras.extend(
        {
            "camera_id": setting["camera_id"],
            "name": setting["display_name"],
            "role": setting["role"],
            "shifts": special_shifts.get(setting["camera_id"], []),
        }
        for setting in settings
        if setting["role"] in {"restroom", "dining"}
    )
    for camera in cameras:
        for shift in camera["shifts"]:
            coverage = shift.get("data_coverage_percent")
            if shift.get("period_status") != "complete":
                coverage_status = "pending"
            elif (
                isinstance(coverage, (int, float))
                and coverage >= args.coverage_threshold
            ):
                coverage_status = "passed"
            else:
                coverage_status = "failed"
            visual = summarize_visual(
                labels[(camera["camera_id"], shift["id"])],
                args.minimum_visual_samples,
                args.exact_threshold,
            )
            if not configuration_verified:
                status = "not_certified"
            elif "failed" in {coverage_status, visual["status"]}:
                status = "failed"
            elif coverage_status != "passed" or visual["status"] != "passed":
                status = "pending"
            else:
                status = "passed"
            rows.append({
                "camera_id": camera["camera_id"],
                "name": camera["name"],
                "role": camera["role"],
                "shift_id": shift["id"],
                "shift_name": shift["name"],
                "period_status": shift["period_status"],
                "coverage_status": coverage_status,
                "data_coverage_percent": coverage,
                "average_occupancy": shift.get("average_occupancy"),
                "staffing_coverage_percent": shift.get(
                    "staffing_coverage_percent"
                ),
                "visual": visual,
                "status": status,
            })

    return {
        "schema_version": 1,
        "day": selected_day.isoformat(),
        "generated_at": report["generated_at"],
        "database_integrity": integrity,
        "configuration_history": (
            "verified_for_day"
            if configuration_verified
            else "historical_configuration_unverified"
        ),
        "thresholds": {
            "coverage_percent": args.coverage_threshold,
            "exact_visual_percent": args.exact_threshold,
            "minimum_visual_samples_per_camera_shift": (
                args.minimum_visual_samples
            ),
        },
        "camera_shifts": rows,
        "summary": {
            "passed": sum(row["status"] == "passed" for row in rows),
            "failed": sum(row["status"] == "failed" for row in rows),
            "pending": sum(row["status"] == "pending" for row in rows),
            "not_certified": sum(
                row["status"] == "not_certified" for row in rows
            ),
        },
    }


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Audita datos anonimos por turno usando SQLite en modo lectura"
        )
    )
    parser.add_argument("--database", default="data/aeye.db")
    parser.add_argument("--day", required=True)
    parser.add_argument("--visual-labels", type=Path)
    parser.add_argument("--coverage-threshold", type=float, default=95.0)
    parser.add_argument("--exact-threshold", type=float, default=90.0)
    parser.add_argument("--minimum-visual-samples", type=int, default=10)
    parser.add_argument(
        "--configuration-valid-from",
        type=date.fromisoformat,
        help="Primera fecha con configuracion historica certificable",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    if args.minimum_visual_samples < 1:
        raise SystemExit("--minimum-visual-samples debe ser positivo")
    if not 0 <= args.coverage_threshold <= 100:
        raise SystemExit("--coverage-threshold debe estar entre 0 y 100")
    if not 0 <= args.exact_threshold <= 100:
        raise SystemExit("--exact-threshold debe estar entre 0 y 100")
    print(json.dumps(audit(args), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
