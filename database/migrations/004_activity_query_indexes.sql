CREATE INDEX IF NOT EXISTS idx_occupancy_camera_time
  ON occupancy_samples(camera_id, sampled_at);

