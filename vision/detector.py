"""Carga y ejecuta el engine TensorRT usado para detectar personas."""

import json
import struct
import time
from dataclasses import dataclass
from pathlib import Path

from ultralytics import YOLO

from vision.pipeline import parse_pipeline_settings


@dataclass(frozen=True)
class Detection:
    """Deteccion de persona con caja, confianza y clase para ByteTrack."""

    box: list
    confidence: float
    class_id: int = 0


@dataclass(frozen=True)
class EngineCapabilities:
    """Capacidades declaradas dentro del engine exportado por Ultralytics."""

    batch_size: int
    dynamic: bool
    imgsz: tuple
    precision: str


def normalize_image_size(value):
    """Normaliza `imgsz` a `(alto, ancho)` para entradas fijas TensorRT."""
    if isinstance(value, bool):
        raise ValueError("imgsz debe ser un entero o una lista [alto, ancho]")
    if isinstance(value, int):
        dimensions = (value, value)
    elif isinstance(value, (list, tuple)) and len(value) == 2:
        dimensions = tuple(int(dimension) for dimension in value)
    else:
        raise ValueError("imgsz debe ser un entero o una lista [alto, ancho]")
    if any(dimension <= 0 for dimension in dimensions):
        raise ValueError("Las dimensiones de imgsz deben ser positivas")
    return dimensions


def read_engine_capabilities(path):
    """Lee la metadata prefijada sin deserializar TensorRT ni usar la GPU."""
    engine_path = Path(path)
    with engine_path.open("rb") as stream:
        length_raw = stream.read(4)
        if len(length_raw) != 4:
            raise ValueError(f"Engine TensorRT sin metadata valida: {engine_path}")
        metadata_length = struct.unpack("<I", length_raw)[0]
        if metadata_length < 2 or metadata_length > 1_000_000:
            raise ValueError(f"Metadata TensorRT fuera de rango: {engine_path}")
        metadata_raw = stream.read(metadata_length)
    try:
        metadata = json.loads(metadata_raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Metadata TensorRT ilegible: {engine_path}") from error

    args = metadata.get("args", {})
    imgsz = normalize_image_size(metadata.get("imgsz", []))
    batch_size = int(metadata.get("batch", args.get("batch", 1)))
    quantize = args.get("quantize")
    precision = {8: "int8", 16: "fp16", 32: "fp32"}.get(quantize, "unknown")
    return EngineCapabilities(
        batch_size=batch_size,
        dynamic=bool(args.get("dynamic", False)),
        imgsz=imgsz,
        precision=precision,
    )


def validate_engine_for_batching(system_cfg, batching_settings):
    """Impide iniciar batching con un perfil fijo o demasiado pequeno."""
    path = Path(system_cfg.get("tensorrt_engine", "yolov8n.engine"))
    capabilities = read_engine_capabilities(path)
    expected_imgsz = normalize_image_size(system_cfg.get("imgsz", 640))
    if capabilities.imgsz != expected_imgsz:
        raise ValueError(
            "El engine TensorRT usa imgsz="
            f"{capabilities.imgsz}, pero se solicito {expected_imgsz}"
        )
    if batching_settings.enabled:
        if not capabilities.dynamic:
            raise ValueError(
                "Batching requiere un engine TensorRT con dynamic=true"
            )
        if capabilities.batch_size < batching_settings.max_batch_size:
            raise ValueError(
                "El engine TensorRT admite batch maximo "
                f"{capabilities.batch_size}, pero se solicito "
                f"{batching_settings.max_batch_size}"
            )
    return capabilities


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


def _detections_from_result(result, transfer_mode="split"):
    """Convierte un Result de Ultralytics al formato auditable de AEYE."""
    if result.boxes is None or not len(result.boxes):
        return []
    if transfer_mode == "packed":
        rows = result.boxes.data[:, :6].cpu().tolist()
        return [
            Detection(box=row[:4], confidence=float(row[4]), class_id=int(row[5]))
            for row in rows
        ]
    boxes = result.boxes.xyxy.cpu().tolist()
    confidences = result.boxes.conf.cpu().tolist()
    classes = result.boxes.cls.cpu().tolist()
    return [
        Detection(box=box, confidence=float(confidence), class_id=int(class_id))
        for box, confidence, class_id in zip(boxes, confidences, classes)
    ]


def _timings_from_result(result):
    """Extrae tiempos por imagen reportados por Ultralytics."""
    speed = getattr(result, "speed", None) or {}
    return {
        "preprocess_ms": speed.get("preprocess"),
        "inference_ms": speed.get("inference"),
        "postprocess_ms": speed.get("postprocess"),
    }


def detect_batch(model, frames, system_cfg, with_timing=False):
    """Ejecuta un lote y conserva alineacion uno a uno con sus entradas."""
    if not frames:
        return ([], []) if with_timing else []
    results = model.predict(
        list(frames),
        device=system_cfg["device"],
        classes=[0],
        conf=float(system_cfg["confidence"]),
        imgsz=normalize_image_size(system_cfg["imgsz"]),
        rect=False,
        batch=len(frames),
        verbose=False,
    )
    if len(results) != len(frames):
        raise RuntimeError(
            f"TensorRT devolvio {len(results)} resultados para {len(frames)} frames"
        )
    transfer_mode = parse_pipeline_settings(system_cfg).result_transfer
    detections = []
    conversion_times = []
    for result in results:
        conversion_started = time.perf_counter()
        detections.append(_detections_from_result(result, transfer_mode))
        conversion_times.append(
            (time.perf_counter() - conversion_started) * 1000.0
        )
    if not with_timing:
        return detections
    timings = []
    for result, conversion_ms in zip(results, conversion_times):
        row = _timings_from_result(result)
        row["result_conversion_ms"] = conversion_ms
        timings.append(row)
    return detections, timings


def detect(model, frame, system_cfg, with_timing=False):
    """Conserva la API individual usando internamente la ruta por lotes."""
    output = detect_batch(model, [frame], system_cfg, with_timing=with_timing)
    if not with_timing:
        return output[0]
    detections, timings = output
    return detections[0], timings[0]
