BEGIN;

DROP INDEX IF EXISTS idx_occupancy_zone_time;
ALTER TABLE occupancy_samples RENAME TO occupancy_samples_legacy;

CREATE TABLE occupancy_samples (
  id INTEGER PRIMARY KEY,
  camera_id TEXT NOT NULL,
  zone TEXT NOT NULL,
  sampled_at TEXT NOT NULL,
  people_count INTEGER,
  raw_people_count INTEGER,
  minimum INTEGER NOT NULL,
  maximum INTEGER NOT NULL,
  data_status TEXT NOT NULL CHECK(data_status IN ('valid','no_data')),
  status TEXT NOT NULL CHECK(status IN ('ok','missing','extra','unknown'))
);

INSERT INTO occupancy_samples(
  id,camera_id,zone,sampled_at,people_count,raw_people_count,
  minimum,maximum,data_status,status
)
SELECT id,camera_id,zone,sampled_at,people_count,people_count,
       minimum,maximum,'valid',status
FROM occupancy_samples_legacy;

DROP TABLE occupancy_samples_legacy;
CREATE INDEX idx_occupancy_zone_time ON occupancy_samples(zone, sampled_at);
CREATE INDEX idx_occupancy_camera_time ON occupancy_samples(camera_id, sampled_at);
CREATE INDEX idx_occupancy_quality_time ON occupancy_samples(data_status, sampled_at);

ALTER TABLE incidents ADD COLUMN closure_reason TEXT;

COMMIT;
