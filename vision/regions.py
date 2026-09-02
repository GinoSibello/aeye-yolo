"""Filtra tracks por ROI y detecta cruces de una linea normalizada."""

import math
import time
from dataclasses import dataclass


def bottom_center(box, frame_shape):
    """Devuelve el punto de apoyo normalizado de una caja."""
    height, width = frame_shape[:2]
    x1, _, x2, y2 = box
    return ((float(x1) + float(x2)) / (2.0 * width), float(y2) / height)


def point_in_polygon(point, polygon):
    """Aplica ray casting para una ROI normalizada."""
    x, y = point
    inside = False
    previous = polygon[-1]
    for current in polygon:
        x1, y1 = previous
        x2, y2 = current
        if (y1 > y) != (y2 > y):
            crossing = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < crossing:
                inside = not inside
        previous = current
    return inside


def tracks_in_roi(tracks, frame_shape, polygon):
    """Conserva tracks cuyo punto de apoyo esta dentro del puesto."""
    if not polygon:
        return list(tracks)
    return [
        track
        for track in tracks
        if point_in_polygon(bottom_center(track.box, frame_shape), polygon)
    ]


@dataclass(frozen=True)
class AccessEvent:
    """Cruce anonimo observado en una entrada o salida."""

    event_type: str
    track_id: str
    confidence: float


class AccessLineTracker:
    """Convierte cambios de lado estables en entradas y salidas anonimas."""

    def __init__(self, settings=None):
        settings = settings or {}
        self.enabled = bool(settings.get("enabled", False))
        self.start = tuple(settings.get("start", (0.0, 0.5)))
        self.end = tuple(settings.get("end", (1.0, 0.5)))
        self.inside_side = settings.get("inside_side", "left")
        self.hysteresis = max(0.001, float(settings.get("hysteresis", 0.015)))
        self.track_timeout_seconds = max(
            1.0, float(settings.get("track_timeout_seconds", 10))
        )
        self.state = {}
        length = math.hypot(
            self.end[0] - self.start[0],
            self.end[1] - self.start[1],
        )
        if self.enabled and length == 0:
            raise ValueError("La linea de acceso no puede tener longitud cero")
        self.length = length or 1.0

    def _side(self, point):
        """Calcula distancia firmada: positiva es lado izquierdo."""
        ax, ay = self.start
        bx, by = self.end
        px, py = point
        return ((bx - ax) * (py - ay) - (by - ay) * (px - ax)) / self.length

    def update(self, tracks, frame_shape, now=None):
        """Devuelve cruces confirmados sin asignar identidad persistente."""
        if not self.enabled:
            return []
        timestamp = time.monotonic() if now is None else float(now)
        events = []
        active = set()
        for track in tracks:
            track_id = str(track.track_id)
            active.add(track_id)
            signed = self._side(bottom_center(track.box, frame_shape))
            if abs(signed) < self.hysteresis:
                previous = self.state.get(track_id)
                if previous:
                    previous["last_seen"] = timestamp
                continue
            side = "left" if signed > 0 else "right"
            previous = self.state.get(track_id)
            if previous is None:
                self.state[track_id] = {"side": side, "last_seen": timestamp}
                continue
            if previous["side"] != side:
                entering = side == self.inside_side
                events.append(AccessEvent(
                    "entry" if entering else "exit",
                    track_id,
                    0.8,
                ))
                previous["side"] = side
            previous["last_seen"] = timestamp

        cutoff = timestamp - self.track_timeout_seconds
        self.state = {
            key: value
            for key, value in self.state.items()
            if value["last_seen"] >= cutoff or key in active
        }
        return events
