"""Registra muestras auditables y administra incidentes confirmados."""

from datetime import datetime


class MetricsRecorder:
    """Reduce muestras y sincroniza transiciones confirmadas con SQLite."""

    def __init__(self, repository, sample_every_seconds=5):
        self.repository = repository
        self.sample_every_seconds = float(sample_every_seconds)
        self.last_sample = {}
        self.open_incidents = {}

    def recover_after_restart(self):
        """Cierra incidentes heredados sin inventar datos durante el apagado."""
        recovered = 0
        for incident in self.repository.open_incidents():
            started = datetime.fromisoformat(incident["started_at"])
            last_valid = self.repository.last_valid_sample(incident["camera_id"])
            ended = datetime.fromisoformat(last_valid) if last_valid else started
            if ended < started:
                ended = started
            self.repository.recover_incident(
                incident["id"], ended, reason="process_restart"
            )
            recovered += 1
        return recovered

    def observe(self, camera, observation, at=None):
        """Guarda una observacion y aplica su apertura/cierre de incidente."""
        now = at or datetime.now().astimezone()
        cam_id = camera["id"]
        minimum = int(camera.get("min_people", 0))
        maximum = int(camera.get("max_people", 9999))

        last = self.last_sample.get(cam_id)
        if last is None or (now - last).total_seconds() >= self.sample_every_seconds:
            self.repository.add_occupancy(
                cam_id,
                camera.get("zone", ""),
                now,
                observation.raw_count,
                observation.smoothed_count,
                minimum,
                maximum,
                observation.data_status,
                observation.staffing_status,
            )
            self.last_sample[cam_id] = now

        transition = observation.transition or {}
        current = self.open_incidents.get(cam_id)
        if transition.get("type") == "closed" and current:
            self.repository.recover_incident(
                current["id"], now, reason=transition.get("reason", "recovered")
            )
            del self.open_incidents[cam_id]
        elif transition.get("type") == "opened":
            if current:
                self.repository.recover_incident(
                    current["id"], now, reason="status_changed"
                )
            kind = transition["kind"]
            incident_id = self.repository.start_incident(
                cam_id,
                camera.get("zone", ""),
                kind,
                now,
                minimum,
                maximum,
                observation.smoothed_count,
            )
            self.open_incidents[cam_id] = {"id": incident_id, "kind": kind}
        return observation.staffing_status

    def mark_alerted(self, camera_id, at=None):
        """Asocia la hora de alerta con el incidente abierto."""
        incident = self.open_incidents.get(camera_id)
        if incident:
            self.repository.alert_incident(
                incident["id"], at or datetime.now().astimezone()
            )
