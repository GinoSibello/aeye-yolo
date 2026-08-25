"""Carga y ejecuta el engine TensorRT usado para detectar personas."""

from dataclasses import dataclass
from pathlib import Path

from ultralytics import YOLO


@dataclass(frozen=True)
class Detection:
    """Deteccion de persona con caja, confianza y clase para ByteTrack."""

    box: list
    confidence: float
    class_id: int = 0


def load_detector(system_cfg):
    """Carga una sola vez el engine TensorRT configurado."""
    model_path = system_cfg.get("tensorrt_engine", "yolov8n.engine")
    path = Path(model_path)
    if not path.is_file():
        raise FileNotFoundError(
            f"No existe el engine TensorRT: {path}. Copie un engine compatible "
            "generado en esta Jetson y con la misma versión de TensorRT."
        )
    if path.suffix != ".engine":
        raise ValueError("tensorrt_engine debe apuntar a un archivo .engine")

    return YOLO(str(path))


def _detections_from_results(results):
    """Convierte Results de Ultralytics al formato auditable usado por AEYE."""
    result = results[0]
    if result.boxes is None or not len(result.boxes):
        return []
    boxes = result.boxes.xyxy.cpu().tolist()
    confidences = result.boxes.conf.cpu().tolist()
    classes = result.boxes.cls.cpu().tolist()
    return [
        Detection(box=box, confidence=float(confidence), class_id=int(class_id))
        for box, confidence, class_id in zip(boxes, confidences, classes)
    ]


def detect(model, frame, system_cfg, with_timing=False):
    """Ejecuta TensorRT y, opcionalmente, expone sus tiempos internos."""
    results = model.predict(
        frame,
        device=system_cfg["device"],
        classes=[0],
        conf=float(system_cfg["confidence"]),
        imgsz=int(system_cfg["imgsz"]),
        rect=False,
        verbose=False,
    )
    detections = _detections_from_results(results)
    if not with_timing:
        return detections

    speed = getattr(results[0], "speed", None) or {}
    timings = {
        "preprocess_ms": speed.get("preprocess"),
        "inference_ms": speed.get("inference"),
        "postprocess_ms": speed.get("postprocess"),
    }
    return detections, timings
