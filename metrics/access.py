"""Persiste cruces anonimos y empareja visitas por orden temporal."""

from datetime import datetime


class AccessRecorder:
    """Registra eventos sin enlazarlos con puestos ni empleados."""

    def __init__(self, repository, run_id):
        self.repository = repository
        self.run_id = run_id

    def recover_after_restart(self):
        """Invalida visitas abiertas porque no pueden cruzar un reinicio."""
        return self.repository.abort_open_visits("process_restart")

    def observe(self, camera_id, event, at=None):
        """Guarda un cruce y mantiene una cola FIFO anonima por camara."""
        now = at or datetime.now().astimezone()
        event_id = self.repository.add_access_event(
            self.run_id,
            camera_id,
            event.event_type,
            now,
            event.track_id,
            event.confidence,
        )
        if event.event_type == "entry":
            open_count = self.repository.open_visit_count(camera_id)
            confidence = 0.7 if open_count == 0 else 0.4
            self.repository.start_anonymous_visit(
                camera_id,
                now,
                event_id,
                confidence,
            )
            return {"type": "entry", "paired": False}
        visit = self.repository.close_oldest_anonymous_visit(
            camera_id,
            now,
            event_id,
        )
        return {
            "type": "exit",
            "paired": visit is not None,
            "visit_id": visit["id"] if visit else None,
        }
