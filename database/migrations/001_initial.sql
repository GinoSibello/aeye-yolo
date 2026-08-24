PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS employees (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cameras (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  zone TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  last_seen TEXT
);

CREATE TABLE IF NOT EXISTS identity_bindings (
  id INTEGER PRIMARY KEY,
  camera_id TEXT NOT NULL,
  track_id TEXT NOT NULL,
  employee_id TEXT NOT NULL,
  confidence REAL NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
  source TEXT NOT NULL,
  identified_at TEXT NOT NULL,
  last_seen TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  FOREIGN KEY(employee_id) REFERENCES employees(id)
);
CREATE INDEX IF NOT EXISTS idx_binding_track ON identity_bindings(camera_id, track_id, expires_at);

CREATE TABLE IF NOT EXISTS occupancy_samples (
  id INTEGER PRIMARY KEY,
  camera_id TEXT NOT NULL,
  zone TEXT NOT NULL,
  sampled_at TEXT NOT NULL,
  people_count INTEGER NOT NULL,
  minimum INTEGER NOT NULL,
  maximum INTEGER NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('ok','missing','extra'))
);
CREATE INDEX IF NOT EXISTS idx_occupancy_zone_time ON occupancy_samples(zone, sampled_at);

CREATE TABLE IF NOT EXISTS zone_sessions (
  id INTEGER PRIMARY KEY,
  employee_id TEXT NOT NULL,
  zone TEXT NOT NULL,
  camera_id TEXT NOT NULL,
  entered_at TEXT NOT NULL,
  exited_at TEXT,
  duration_seconds REAL,
  FOREIGN KEY(employee_id) REFERENCES employees(id)
);
CREATE INDEX IF NOT EXISTS idx_sessions_employee_time ON zone_sessions(employee_id, entered_at);

CREATE TABLE IF NOT EXISTS zone_transitions (
  id INTEGER PRIMARY KEY,
  employee_id TEXT NOT NULL,
  from_zone TEXT NOT NULL,
  to_zone TEXT NOT NULL,
  transitioned_at TEXT NOT NULL,
  FOREIGN KEY(employee_id) REFERENCES employees(id)
);
CREATE INDEX IF NOT EXISTS idx_transitions_time ON zone_transitions(transitioned_at);

CREATE TABLE IF NOT EXISTS incidents (
  id INTEGER PRIMARY KEY,
  camera_id TEXT NOT NULL,
  zone TEXT NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN ('missing','extra')),
  started_at TEXT NOT NULL,
  alerted_at TEXT,
  recovered_at TEXT,
  duration_seconds REAL,
  min_expected INTEGER NOT NULL,
  max_expected INTEGER NOT NULL,
  people_count INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_incidents_time ON incidents(started_at);

CREATE TABLE IF NOT EXISTS detection_reviews (
  id INTEGER PRIMARY KEY,
  camera_id TEXT NOT NULL,
  detection_at TEXT NOT NULL,
  is_false_positive INTEGER NOT NULL CHECK(is_false_positive IN (0,1)),
  reviewer TEXT,
  notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_reviews_camera_time ON detection_reviews(camera_id, detection_at);
