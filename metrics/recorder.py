"""Registra muestras de dotacion y administra incidentes."""

from datetime import datetime


class MetricsRecorder:
    """Reduce muestras y mantiene incidentes abiertos por camara."""
    def __init__(self, repository, sample_every_seconds=5):
        """Configura repositorio e intervalo minimo entre muestras."""
        self.repository = repository
        self.sample_every_seconds = sample_every_seconds
        self.last_sample = {}
        self.open_incidents = {}

    def observe_staffing(self, camera, count, at=None):
        """Guarda ocupacion y abre, cambia o cierra el incidente activo."""
        now = at or datetime.now().astimezone()
        cam_id = camera["id"]
        minimum = int(camera.get("min_people", 0))
        maximum = int(camera.get("max_people", 9999))
        status = "missing" if count < minimum else "extra" if count > maximum else "ok"

        last = self.last_sample.get(cam_id)
        if last is None or (now - last).total_seconds() >= self.sample_every_seconds:
            self.repository.add_occupancy(cam_id, camera.get("zone", ""), now, count, minimum, maximum)
            self.last_sample[cam_id] = now

        current = self.open_incidents.get(cam_id)
        if status == "ok" and current:
            self.repository.recover_incident(current["id"], now)
            del self.open_incidents[cam_id]
        elif status != "ok" and (not current or current["kind"] != status):
            if current:
                self.repository.recover_incident(current["id"], now)
            incident_id = self.repository.start_incident(
                cam_id, camera.get("zone", ""), status, now, minimum, maximum, count
            )
            self.open_incidents[cam_id] = {"id": incident_id, "kind": status}
        return status

    def mark_alerted(self, camera_id, at=None):
        """Asocia la hora de alerta con el incidente abierto."""
        incident = self.open_incidents.get(camera_id)
        if incident:
            self.repository.alert_incident(incident["id"], at or datetime.now().astimezone())
