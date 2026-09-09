ALTER TABLE workplace_settings
  ADD COLUMN shifts_json TEXT NOT NULL DEFAULT '[]';
