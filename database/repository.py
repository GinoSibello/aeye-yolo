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
