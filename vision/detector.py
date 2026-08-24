"""Carga y ejecuta el engine TensorRT usado para detectar personas."""

from pathlib import Path

from ultralytics import YOLO


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


def _boxes_from_results(results):
    """Convierte Results de Ultralytics al formato usado por el tracker."""
    result = results[0]
    if result.boxes is None or not len(result.boxes):
        return []
    return result.boxes.xyxy.cpu().tolist()


def detect(model, frame, system_cfg):
    """Ejecuta TensorRT con entrada fija y devuelve cajas de personas."""
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
