BEGIN;

CREATE TABLE workplace_settings (
  camera_id TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  zone TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('workstation','restroom','dining','other')),
  reporting_enabled INTEGER NOT NULL DEFAULT 1 CHECK(reporting_enabled IN (0,1)),
  expected_people INTEGER CHECK(expected_people IS NULL OR expected_people >= 0),
  timezone TEXT NOT NULL,
  workdays_json TEXT NOT NULL,
  shift_start TEXT,
  shift_end TEXT,
  arrival_grace_minutes REAL NOT NULL DEFAULT 5,
  early_departure_tolerance_minutes REAL NOT NULL DEFAULT 5,
  overtime_tolerance_minutes REAL NOT NULL DEFAULT 10,
  overtime_observation_minutes REAL NOT NULL DEFAULT 180,
  meal_window_start TEXT,
  meal_window_end TEXT,
  meal_allowed_minutes REAL,
  max_sample_gap_seconds REAL NOT NULL DEFAULT 15,
  absence_merge_gap_minutes REAL NOT NULL DEFAULT 2,
  track_session_gap_seconds REAL NOT NULL DEFAULT 15,
  roi_json TEXT NOT NULL,
  access_line_json TEXT NOT NULL,
  configuration_status TEXT NOT NULL CHECK(configuration_status IN ('ready','partial','pending')),
  updated_at TEXT NOT NULL,
  FOREIGN KEY(camera_id) REFERENCES cameras(id)
);
CREATE INDEX idx_workplace_role ON workplace_settings(role, reporting_enabled);

CREATE TABLE anonymous_track_observations (
  id INTEGER PRIMARY KEY,
  run_id TEXT NOT NULL,
  camera_id TEXT NOT NULL,
  sampled_at TEXT NOT NULL,
  track_id TEXT NOT NULL,
  UNIQUE(run_id, camera_id, sampled_at, track_id)
);
CREATE INDEX idx_track_observation_camera_time
  ON anonymous_track_observations(camera_id, sampled_at);
CREATE INDEX idx_track_observation_session
  ON anonymous_track_observations(run_id, camera_id, track_id, sampled_at);

CREATE TABLE access_events (
  id INTEGER PRIMARY KEY,
  run_id TEXT NOT NULL,
  camera_id TEXT NOT NULL,
  event_type TEXT NOT NULL CHECK(event_type IN ('entry','exit')),
  observed_at TEXT NOT NULL,
  track_id TEXT NOT NULL,
  confidence REAL NOT NULL CHECK(confidence >= 0 AND confidence <= 1)
);
CREATE INDEX idx_access_events_camera_time
  ON access_events(camera_id, observed_at);

CREATE TABLE anonymous_visits (
  id INTEGER PRIMARY KEY,
  camera_id TEXT NOT NULL,
  entered_at TEXT NOT NULL,
  exited_at TEXT,
  duration_seconds REAL,
  entry_event_id INTEGER,
  exit_event_id INTEGER,
  pairing_method TEXT NOT NULL DEFAULT 'fifo',
  confidence REAL NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
  status TEXT NOT NULL CHECK(status IN ('open','completed','aborted')),
  closure_reason TEXT,
  FOREIGN KEY(entry_event_id) REFERENCES access_events(id),
  FOREIGN KEY(exit_event_id) REFERENCES access_events(id)
);
CREATE INDEX idx_anonymous_visits_camera_time
  ON anonymous_visits(camera_id, entered_at, exited_at);
CREATE INDEX idx_anonymous_visits_open
  ON anonymous_visits(camera_id, status, entered_at);

COMMIT;
