"""Valida asociaciones entre tracks e identidades no biometricas."""

from datetime import datetime, timedelta

from database.models import IdentityBinding


class IdentityManager:
    """Crea y resuelve vinculos temporales con evidencia externa permitida."""
    def __init__(self, repository, ttl_seconds=30, minimum_confidence=0.9):
        """Configura persistencia, vigencia y confianza minima del vinculo."""
        self.repository = repository
        self.ttl_seconds = ttl_seconds
        self.minimum_confidence = minimum_confidence

    def bind(self, camera_id, track_id, employee_id, confidence, source, at=None):
        """Valida la fuente y registra una identidad temporal para un track."""
        if confidence < self.minimum_confidence:
            raise ValueError("Evidencia de identidad por debajo de la confianza mínima")
        if source not in {"badge", "qr", "apriltag", "aruco", "rfid", "uwb", "access_control"}:
            raise ValueError("Fuente de identidad no verificable")
        now = at or datetime.now().astimezone()
        binding = IdentityBinding(camera_id, track_id, employee_id, confidence, source,
                                  now, now, now + timedelta(seconds=self.ttl_seconds))
        self.repository.bind_identity(binding)
        return binding

    def resolve(self, camera_id, track_id, at=None):
        """Devuelve la identidad vigente o None cuando no existe."""
        return self.repository.active_identity(camera_id, track_id, at or datetime.now().astimezone())
