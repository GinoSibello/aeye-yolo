"""Capa de persistencia SQLite para configuracion, metricas e identidad."""

import sqlite3
import threading
from datetime import datetime
from pathlib import Path


def _iso(value):
    """Normaliza fechas y valores escalares a texto apto para SQLite."""
    return value.isoformat(timespec="seconds") if isinstance(value, datetime) else str(value)


class Repository:
    """Repositorio SQLite thread-safe. Las consultas usan intervalos [desde, hasta)."""

    def __init__(self, path):
        """Prepara la ruta, el almacenamiento por hilo y las migraciones."""
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self.migrate()

    def connection(self):
        """Devuelve una conexion SQLite independiente para el hilo actual."""
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(str(self.path), timeout=10)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys=ON")
            self._local.conn = conn
        return conn

    def migrate(self):
        """Aplica una sola vez cada migracion SQL, en orden de nombre."""
        migrations_dir = Path(__file__).parent / "migrations"
        conn = sqlite3.connect(str(self.path))
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations "
                "(name TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
            for migration in sorted(migrations_dir.glob("*.sql")):
                applied = conn.execute(
                    "SELECT 1 FROM schema_migrations WHERE name=?", (migration.name,)
                ).fetchone()
                if applied:
                    continue
                conn.executescript(migration.read_text(encoding="utf-8"))
                conn.execute(
                    "INSERT INTO schema_migrations(name) VALUES(?)", (migration.name,)
                )
                conn.commit()
        finally:
            conn.close()

    def close(self):
        """Cierra la conexion del hilo actual, importante para pruebas y apagado."""
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    def execute(self, sql, params=()):
        """Ejecuta una escritura parametrizada y confirma la transaccion."""
        conn = self.connection()
        cur = conn.execute(sql, params)
        conn.commit()
        return cur

    def query(self, sql, params=()):
        """Ejecuta una consulta y devuelve sus filas como diccionarios."""
        return [dict(row) for row in self.connection().execute(sql, params).fetchall()]

    def upsert_camera(self, camera, seen_at):
        """Crea o actualiza el inventario y ultima aparicion de una camara."""
        self.execute(
            """INSERT INTO cameras(id,name,zone,enabled,created_at,last_seen) VALUES(?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET name=excluded.name, zone=excluded.zone,
            enabled=excluded.enabled, last_seen=excluded.last_seen""",
            (camera["id"], camera["name"], camera.get("zone", ""), int(camera.get("enabled", True)),
             _iso(seen_at), _iso(seen_at)),
        )

    def upsert_workplace(self, settings):
        """Materializa nombres, roles y horarios usados por los reportes."""
        self.execute(
            """INSERT INTO workplace_settings(
            camera_id,display_name,zone,role,reporting_enabled,expected_people,
            timezone,workdays_json,shift_start,shift_end,arrival_grace_minutes,
            early_departure_tolerance_minutes,overtime_tolerance_minutes,
            overtime_observation_minutes,meal_window_start,meal_window_end,
            meal_allowed_minutes,max_sample_gap_seconds,absence_merge_gap_minutes,
            track_session_gap_seconds,roi_json,access_line_json,
            configuration_status,updated_at,shifts_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(camera_id) DO UPDATE SET
            display_name=excluded.display_name,zone=excluded.zone,role=excluded.role,
            reporting_enabled=excluded.reporting_enabled,
            expected_people=excluded.expected_people,timezone=excluded.timezone,
            workdays_json=excluded.workdays_json,shift_start=excluded.shift_start,
            shift_end=excluded.shift_end,
            shifts_json=excluded.shifts_json,
            arrival_grace_minutes=excluded.arrival_grace_minutes,
            early_departure_tolerance_minutes=excluded.early_departure_tolerance_minutes,
            overtime_tolerance_minutes=excluded.overtime_tolerance_minutes,
            overtime_observation_minutes=excluded.overtime_observation_minutes,
            meal_window_start=excluded.meal_window_start,
            meal_window_end=excluded.meal_window_end,
            meal_allowed_minutes=excluded.meal_allowed_minutes,
            max_sample_gap_seconds=excluded.max_sample_gap_seconds,
            absence_merge_gap_minutes=excluded.absence_merge_gap_minutes,
            track_session_gap_seconds=excluded.track_session_gap_seconds,
            roi_json=excluded.roi_json,access_line_json=excluded.access_line_json,
            configuration_status=excluded.configuration_status,
            updated_at=excluded.updated_at""",
            (
                settings["camera_id"], settings["display_name"], settings["zone"],
                settings["role"], int(settings["reporting_enabled"]),
                settings["expected_people"], settings["timezone"],
                settings["workdays_json"], settings["shift_start"],
                settings["shift_end"], settings["arrival_grace_minutes"],
                settings["early_departure_tolerance_minutes"],
                settings["overtime_tolerance_minutes"],
                settings["overtime_observation_minutes"],
                settings["meal_window_start"], settings["meal_window_end"],
                settings["meal_allowed_minutes"],
                settings["max_sample_gap_seconds"],
                settings["absence_merge_gap_minutes"],
                settings["track_session_gap_seconds"], settings["roi_json"],
                settings["access_line_json"], settings["configuration_status"],
                _iso(settings["updated_at"]), settings["shifts_json"],
            ),
        )

    def workplaces(self, enabled_only=True):
        """Lista la configuracion efectiva que usa el motor de reportes."""
        where = "WHERE reporting_enabled=1" if enabled_only else ""
        return self.query(
            f"""SELECT * FROM workplace_settings {where}
            ORDER BY CASE role WHEN 'workstation' THEN 0 WHEN 'restroom' THEN 1
            WHEN 'dining' THEN 2 ELSE 3 END,
            display_name COLLATE NOCASE, camera_id"""
        )

    def add_occupancy(
        self, camera_id, zone, sampled_at, raw_count, smoothed_count,
        minimum, maximum, data_status, status,
    ):
        """Guarda conteos crudo/suavizado y distingue datos validos de ausencia."""
        self.execute(
            """INSERT INTO occupancy_samples(
            camera_id,zone,sampled_at,people_count,raw_people_count,
            minimum,maximum,data_status,status) VALUES(?,?,?,?,?,?,?,?,?)""",
            (camera_id, zone, _iso(sampled_at), smoothed_count, raw_count,
             minimum, maximum, data_status, status),
        )
        return status

    def add_track_observations(
        self, run_id, camera_id, sampled_at, track_ids,
    ):
        """Guarda IDs locales como evidencia anonima, aislados por ejecucion."""
        rows = [
            (run_id, camera_id, _iso(sampled_at), str(track_id))
            for track_id in track_ids
        ]
        if not rows:
            return 0
        conn = self.connection()
        conn.executemany(
            """INSERT OR IGNORE INTO anonymous_track_observations(
            run_id,camera_id,sampled_at,track_id) VALUES(?,?,?,?)""",
            rows,
        )
        conn.commit()
        return len(rows)

    def add_access_event(
        self, run_id, camera_id, event_type, observed_at, track_id, confidence,
    ):
        """Persiste un cruce local sin inferir una identidad."""
        return self.execute(
            """INSERT INTO access_events(
            run_id,camera_id,event_type,observed_at,track_id,confidence
            ) VALUES(?,?,?,?,?,?)""",
            (
                run_id, camera_id, event_type, _iso(observed_at),
                str(track_id), float(confidence),
            ),
        ).lastrowid

    def open_visit_count(self, camera_id):
        """Cuenta visitas FIFO aun sin salida observada."""
        return self.query(
            """SELECT COUNT(*) count FROM anonymous_visits
            WHERE camera_id=? AND status='open'""",
            (camera_id,),
        )[0]["count"]

    def start_anonymous_visit(
        self, camera_id, entered_at, entry_event_id, confidence,
    ):
        """Abre una visita anonima a partir de un cruce de entrada."""
        return self.execute(
            """INSERT INTO anonymous_visits(
            camera_id,entered_at,entry_event_id,pairing_method,confidence,status
            ) VALUES(?,?,?,'fifo',?,'open')""",
            (camera_id, _iso(entered_at), entry_event_id, float(confidence)),
        ).lastrowid

    def close_oldest_anonymous_visit(self, camera_id, exited_at, exit_event_id):
        """Empareja una salida con la entrada abierta mas antigua."""
        conn = self.connection()
        visits = conn.execute(
            """SELECT id,entered_at,confidence FROM anonymous_visits
            WHERE camera_id=? AND status='open' ORDER BY entered_at,id""",
            (camera_id,),
        ).fetchall()
        if not visits:
            return None
        visit = visits[0]
        confidence = min(float(visit["confidence"]), 0.7 if len(visits) == 1 else 0.4)
        conn.execute(
            """UPDATE anonymous_visits SET exited_at=?,
            duration_seconds=MAX(0,(julianday(?) - julianday(entered_at))*86400),
            exit_event_id=?,confidence=?,status='completed',
            closure_reason='paired_exit' WHERE id=?""",
            (
                _iso(exited_at), _iso(exited_at), exit_event_id,
                confidence, visit["id"],
            ),
        )
        conn.commit()
        return {"id": visit["id"], "confidence": confidence}

    def abort_open_visits(self, reason):
        """Marca como no medibles las visitas que atravesaron un reinicio."""
        cursor = self.execute(
            """UPDATE anonymous_visits SET status='aborted',closure_reason=?
            WHERE status='open'""",
            (reason,),
        )
        return cursor.rowcount

    def start_incident(self, camera_id, zone, kind, started_at, minimum, maximum, count):
        """Abre un incidente de faltantes o sobrantes y devuelve su ID."""
        return self.execute(
            "INSERT INTO incidents(camera_id,zone,kind,started_at,min_expected,max_expected,people_count) VALUES(?,?,?,?,?,?,?)",
            (camera_id, zone, kind, _iso(started_at), minimum, maximum, count),
        ).lastrowid

    def alert_incident(self, incident_id, alerted_at):
        """Marca el instante en que un incidente genero una alerta."""
        self.execute("UPDATE incidents SET alerted_at=? WHERE id=?", (_iso(alerted_at), incident_id))

    def recover_incident(self, incident_id, recovered_at, reason="recovered"):
        """Cierra un incidente, guarda el motivo y calcula su duracion."""
        self.execute(
            """UPDATE incidents SET recovered_at=?,
            duration_seconds=MAX(0,(julianday(?) - julianday(started_at))*86400),
            closure_reason=? WHERE id=?""",
            (_iso(recovered_at), _iso(recovered_at), reason, incident_id),
        )

    def open_incidents(self):
        """Devuelve incidentes que quedaron abiertos en una ejecucion anterior."""
        return self.query("SELECT * FROM incidents WHERE recovered_at IS NULL ORDER BY id")

    def last_valid_sample(self, camera_id):
        """Obtiene el ultimo instante verificable de una camara."""
        rows = self.query(
            """SELECT sampled_at FROM occupancy_samples
            WHERE camera_id=? AND data_status='valid'
            ORDER BY sampled_at DESC LIMIT 1""",
            (camera_id,),
        )
        return rows[0]["sampled_at"] if rows else None

    def bind_identity(self, binding):
        """Persiste la asociacion temporal entre track e identidad externa."""
        self.execute(
            "INSERT OR IGNORE INTO employees(id,name,created_at) VALUES(?,?,?)",
            (binding.employee_id, binding.employee_id, _iso(binding.identified_at)),
        )
        self.execute(
            """INSERT INTO identity_bindings(camera_id,track_id,employee_id,confidence,source,identified_at,last_seen,expires_at)
            VALUES(?,?,?,?,?,?,?,?)""",
            (binding.camera_id, binding.track_id, binding.employee_id, binding.confidence, binding.source,
             _iso(binding.identified_at), _iso(binding.last_seen), _iso(binding.expires_at)),
        )

    def active_identity(self, camera_id, track_id, at):
        """Busca una identidad que siga vigente para un track local."""
        rows = self.query(
            """SELECT employee_id,confidence,source,expires_at FROM identity_bindings
            WHERE camera_id=? AND track_id=? AND expires_at>=? ORDER BY identified_at DESC LIMIT 1""",
            (camera_id, track_id, _iso(at)),
        )
        return rows[0] if rows else None
