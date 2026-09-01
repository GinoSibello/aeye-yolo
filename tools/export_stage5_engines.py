#!/usr/bin/env python3
"""Exporta la matriz FP16 de Etapa 5 y registra compatibilidad TensorRT."""

import argparse
import hashlib
import json
import shutil
import struct
import traceback
from datetime import datetime
from pathlib import Path

from ultralytics import YOLO


DEFAULT_MODELS = ("yolo11n", "yolo26n", "yolo11s", "yolo26s")
DEFAULT_RESOLUTIONS = ("640x640", "960x544")


def parse_resolution(value):
    """Convierte `ancho x alto` a la tupla `(alto, ancho)` de Ultralytics."""
    try:
        width, height = (int(part) for part in value.lower().split("x", 1))
    except (TypeError, ValueError) as error:
        raise ValueError(f"Resolucion invalida: {value}") from error
    if width <= 0 or height <= 0 or width % 32 or height % 32:
        raise ValueError("Cada dimension debe ser positiva y multiplo de 32")
    return height, width


def read_metadata(path):
    """Lee y normaliza la metadata prefijada por Ultralytics al engine."""
    data = Path(path).read_bytes()
    if len(data) < 4:
        raise ValueError("Engine sin metadata")
    length = struct.unpack("<I", data[:4])[0]
    metadata = json.loads(data[4:4 + length])
    args = metadata.get("args", {})
    quantize = args.get("quantize")
    return {
        "batch": int(metadata.get("batch", args.get("batch", 1))),
        "imgsz": [int(value) for value in metadata.get("imgsz", [])],
        "dynamic": bool(args.get("dynamic", False)),
        "precision": {8: "int8", 16: "fp16", 32: "fp32"}.get(
            quantize,
            str(quantize),
        ),
        "end2end": bool(metadata.get("end2end", args.get("end2end", False))),
        "task": metadata.get("task", args.get("task")),
    }


def sha256(path):
    """Calcula la huella del engine sin cargarlo en memoria completo."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_weight(model_name, weights_dir):
    """Usa un peso local o permite a Ultralytics descargar el oficial."""
    target = weights_dir / f"{model_name}.pt"
    if target.is_file():
        return target
    downloaded_model = YOLO(f"{model_name}.pt")
    downloaded = Path(downloaded_model.ckpt_path)
    if downloaded.resolve() != target.resolve():
        shutil.move(str(downloaded), target)
    return target


def export_engine(model_name, resolution, weights_dir, output_dir, overwrite):
    """Exporta y valida un engine fijo batch 1 FP16."""
    height, width = parse_resolution(resolution)
    output = output_dir / f"{model_name}_fp16_{width}x{height}.engine"
    if output.exists() and not overwrite:
        state = "reused"
    else:
        source = ensure_weight(model_name, weights_dir)
        model = YOLO(str(source))
        exported = Path(model.export(
            format="engine",
            imgsz=(height, width),
            batch=1,
            dynamic=False,
            quantize=16,
            workspace=2,
            device=0,
            simplify=False,
        ))
        output.parent.mkdir(parents=True, exist_ok=True)
        exported.replace(output)
        state = "exported"

    metadata = read_metadata(output)
    if metadata["imgsz"] != [height, width]:
        raise ValueError(
            f"Engine {output.name} usa {metadata['imgsz']}, no {[height, width]}"
        )
    if metadata["batch"] != 1 or metadata["dynamic"]:
        raise ValueError("Etapa 5 requiere engine fijo con batch 1")
    if metadata["precision"] != "fp16":
        raise ValueError(f"Precision inesperada: {metadata['precision']}")
    return {
        "model": model_name,
        "scale": model_name[-1],
        "resolution_width_height": [width, height],
        "engine": str(output),
        "bytes": output.stat().st_size,
        "sha256": sha256(output),
        "status": state,
        **metadata,
    }


def main():
    """Procesa nano antes que small y conserva fallos como evidencia."""
    parser = argparse.ArgumentParser(description="Exportar engines de Etapa 5")
    parser.add_argument("--weights-dir", type=Path, default=Path("models/stage5"))
    parser.add_argument("--output-dir", type=Path, default=Path("models/stage5"))
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--models", nargs="+", default=list(DEFAULT_MODELS))
    parser.add_argument(
        "--resolutions",
        nargs="+",
        default=list(DEFAULT_RESOLUTIONS),
    )
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    args.weights_dir.mkdir(parents=True, exist_ok=True)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for model_name in args.models:
        for resolution in args.resolutions:
            print(f"EXPORT model={model_name} resolution={resolution}", flush=True)
            try:
                rows.append(export_engine(
                    model_name,
                    resolution,
                    args.weights_dir,
                    args.output_dir,
                    args.overwrite,
                ))
            except Exception as error:
                traceback.print_exc()
                rows.append({
                    "model": model_name,
                    "resolution": resolution,
                    "status": "failed",
                    "error": str(error),
                })

    payload = {
        "schema_version": 1,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "precision_policy": "fp16_only",
        "engines": rows,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    successful = [row for row in rows if row["status"] != "failed"]
    print(f"engines_ok={len(successful)} engines_failed={len(rows) - len(successful)}")
    if not successful:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
