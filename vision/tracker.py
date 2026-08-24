"""Adaptador de ByteTrack con una instancia independiente por camara."""

from dataclasses import dataclass
from types import SimpleNamespace


@dataclass(frozen=True)
class TrackedDetection:
    """Caja visible asociada a un ID temporal de ByteTrack."""

    box: list
    track_id: int
    confidence: float


def tracked_detections(rows):
    """Convierte la matriz de ByteTrack a objetos simples usados por AEYE."""
    return [
        TrackedDetection(
            box=[float(value) for value in row[:4]],
            track_id=int(row[4]),
            confidence=float(row[5]),
        )
        for row in rows
    ]


class ByteTrackAdapter:
    """Alimenta ByteTrack con detecciones de TensorRT sin compartir estado."""

    def __init__(self, tracker_cfg):
        """Crea el tracker usando umbrales configurables y valores seguros."""
        try:
            from ultralytics.trackers.byte_tracker import BYTETracker
        except ImportError as error:
            raise RuntimeError(
                "La instalacion de Ultralytics no incluye ByteTrack. "
                "Reconstruya la imagen Docker."
            ) from error

        args = SimpleNamespace(
            tracker_type="bytetrack",
            track_high_thresh=float(tracker_cfg.get("track_high_thresh", 0.5)),
            track_low_thresh=float(tracker_cfg.get("track_low_thresh", 0.1)),
            new_track_thresh=float(tracker_cfg.get("new_track_thresh", 0.5)),
            track_buffer=int(tracker_cfg.get("track_buffer", 30)),
            match_thresh=float(tracker_cfg.get("match_thresh", 0.8)),
            fuse_score=bool(tracker_cfg.get("fuse_score", True)),
        )
        self._tracker = BYTETracker(args)
        self._local_ids = {}
        self._next_local_id = 1

    def update(self, detections, frame_shape):
        """Actualiza trayectorias y devuelve solo tracks visibles en este frame."""
        import torch
        from ultralytics.engine.results import Boxes

        if detections:
            values = [
                [*detection.box, detection.confidence, detection.class_id]
                for detection in detections
            ]
            tensor = torch.tensor(values, dtype=torch.float32)
        else:
            tensor = torch.empty((0, 6), dtype=torch.float32)

        boxes = Boxes(tensor, tuple(frame_shape[:2]))
        visible = []
        for track in tracked_detections(self._tracker.update(boxes)):
            if track.track_id not in self._local_ids:
                self._local_ids[track.track_id] = self._next_local_id
                self._next_local_id += 1
            visible.append(
                TrackedDetection(
                    track.box,
                    self._local_ids[track.track_id],
                    track.confidence,
                )
            )
        retained_ids = {
            int(track.track_id)
            for track in self._tracker.tracked_stracks + self._tracker.lost_stracks
        }
        self._local_ids = {
            native_id: local_id
            for native_id, local_id in self._local_ids.items()
            if native_id in retained_ids
        }
        return visible
