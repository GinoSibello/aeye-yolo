"""Planificacion de lotes entre camaras con limites temporales explicitos."""

from dataclasses import dataclass


@dataclass(frozen=True)
class BatchingSettings:
    """Configuracion validada del scheduler de inferencia."""

    enabled: bool = False
    max_batch_size: int = 1
    timeout_ms: int = 0


def parse_batching_settings(system_cfg):
    """Normaliza batching conservando la ruta secuencial como predeterminada."""
    values = dict(system_cfg.get("batching", {}) or {})
    enabled = bool(values.get("enabled", False))
    max_batch_size = int(values.get("max_batch_size", 8 if enabled else 1))
    timeout_ms = int(values.get("timeout_ms", 10 if enabled else 0))
    if max_batch_size < 1:
        raise ValueError("batching.max_batch_size debe ser al menos 1")
    if enabled and max_batch_size < 2:
        raise ValueError("Batching habilitado requiere max_batch_size >= 2")
    if timeout_ms < 0 or timeout_ms > 1000:
        raise ValueError("batching.timeout_ms debe estar entre 0 y 1000")
    return BatchingSettings(
        enabled=enabled,
        max_batch_size=max_batch_size if enabled else 1,
        timeout_ms=timeout_ms if enabled else 0,
    )


class BatchScheduler:
    """Agrupa vencimientos cercanos sin ejecutar una camara antes de tiempo."""

    def __init__(self, camera_ids, inference_fps, settings):
        if float(inference_fps) <= 0:
            raise ValueError("inference_fps_per_camera debe ser mayor que cero")
        self.camera_ids = list(camera_ids)
        self.settings = settings
        self.interval = 1.0 / float(inference_fps)
        self.next_inference = {camera_id: 0.0 for camera_id in self.camera_ids}

    def due(self, now):
        """Devuelve camaras vencidas ordenadas por deadline y orden estable."""
        order = {camera_id: index for index, camera_id in enumerate(self.camera_ids)}
        rows = [
            camera_id
            for camera_id in self.camera_ids
            if now >= self.next_inference[camera_id]
        ]
        return sorted(
            rows,
            key=lambda camera_id: (self.next_inference[camera_id], order[camera_id]),
        )

    def window_deadline(self, now):
        """Fija el limite de espera del lote abierto."""
        return now + self.settings.timeout_ms / 1000.0

    def wait_seconds(self, now, deadline):
        """Calcula una espera corta hasta el proximo vencimiento o timeout."""
        remaining = max(0.0, deadline - now)
        future = [
            due_at - now
            for due_at in self.next_inference.values()
            if now < due_at <= deadline
        ]
        if future:
            remaining = min(remaining, min(future))
        return min(remaining, 0.005)

    def schedule(self, camera_ids, now):
        """Avanza deadlines y devuelve el retraso previo de cada camara."""
        lags = {}
        for camera_id in camera_ids:
            scheduled_at = self.next_inference[camera_id]
            lags[camera_id] = (
                max(0.0, (now - scheduled_at) * 1000.0)
                if scheduled_at > 0.0
                else 0.0
            )
            self.next_inference[camera_id] = now + self.interval
        return lags

    def idle_sleep_seconds(self, now):
        """Evita busy-wait sin retrasar significativamente el siguiente turno."""
        if not self.next_inference:
            return 0.005
        return min(0.005, max(0.0, min(self.next_inference.values()) - now))
