"""Backends intercambiables de detección YOLO.

Ambos caminos devuelven exactamente el mismo formato: una lista de cajas
``[x1, y1, x2, y2]``. De esta forma tracking, staffing y métricas no necesitan
saber si la inferencia se hizo con PyTorch o TensorRT.
"""

from pathlib import Path

from ultralytics import YOLO


SUPPORTED_BACKENDS = {"pytorch", "tensorrt"}


def load_detector(system_cfg):
    """Carga una sola vez el modelo correspondiente al backend configurado."""
    backend = str(system_cfg.get("inference_backend", "pytorch")).lower()
    if backend not in SUPPORTED_BACKENDS:
        raise ValueError(
            f"inference_backend={backend!r} no es válido; use 'pytorch' o 'tensorrt'"
        )

    model_path = (
        system_cfg["model"]
        if backend == "pytorch"
        else system_cfg.get("tensorrt_engine", "yolov8n.engine")
    )
    path = Path(model_path)
    if not path.is_file():
        hint = " Ejecute: python3 tools/export_tensorrt.py" if backend == "tensorrt" else ""
        raise FileNotFoundError(f"No existe el modelo para {backend}: {path}.{hint}")
    if backend == "pytorch" and path.suffix != ".pt":
        raise ValueError("El backend pytorch necesita un modelo .pt")
    if backend == "tensorrt" and path.suffix != ".engine":
        raise ValueError("El backend tensorrt necesita un modelo .engine")

    return backend, YOLO(str(path))


def _boxes_from_results(results):
    """Convierte Results de Ultralytics al formato usado por el tracker."""
    result = results[0]
    if result.boxes is None or not len(result.boxes):
        return []
    return result.boxes.xyxy.cpu().tolist()


def detect_yolo(model, frame, system_cfg):
    """Inferencia original con el archivo PyTorch .pt, sin cambiar su lógica."""
    results = model.predict(
        frame,
        device=system_cfg["device"],
        classes=[0],
        conf=float(system_cfg["confidence"]),
        imgsz=int(system_cfg["imgsz"]),
        verbose=False,
    )
    return _boxes_from_results(results)


def detect_tensorrt(model, frame, system_cfg):
    """Inferencia con un engine TensorRT y salida compatible con detect_yolo."""
    results = model.predict(
        frame,
        device=system_cfg["device"],
        classes=[0],
        conf=float(system_cfg["confidence"]),
        imgsz=int(system_cfg["imgsz"]),
        rect=False,
        verbose=False,
    )
    return _boxes_from_results(results)


def detect(backend, model, frame, system_cfg):
    """Selecciona una de las dos funciones anteriores."""
    if backend == "pytorch":
        return detect_yolo(model, frame, system_cfg)
    if backend == "tensorrt":
        return detect_tensorrt(model, frame, system_cfg)
    raise ValueError(f"Backend de inferencia desconocido: {backend}")
