"""Exporta el modelo PyTorch de AEYE a un engine TensorRT en la Jetson."""

import argparse
import json
from pathlib import Path

from ultralytics import YOLO


def arguments():
    """Define y procesa las opciones de exportacion de linea de comandos."""
    parser = argparse.ArgumentParser(description="Exportar YOLO a TensorRT")
    parser.add_argument("--config", default="cameras.json")
    parser.add_argument("--model", help="Sobrescribe system.model")
    parser.add_argument("--imgsz", type=int, help="Sobrescribe system.imgsz")
    parser.add_argument("--workspace", type=float, default=2.0, help="Workspace máximo en GiB")
    parser.add_argument("--fp32", action="store_true", help="Usar FP32 en lugar de FP16")
    return parser.parse_args()


def main():
    """Valida el modelo y exporta un engine TensorRT fijo para la Jetson."""
    args = arguments()
    config_path = Path(args.config)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    system = config["system"]
    model_path = Path(args.model or system["model"])
    imgsz = args.imgsz or int(system["imgsz"])

    if not model_path.is_file():
        raise FileNotFoundError(f"No existe el modelo PyTorch: {model_path}")
    if model_path.suffix != ".pt":
        raise ValueError("La exportación debe comenzar desde un modelo .pt")

    precision = 32 if args.fp32 else 16
    print(f"Exportando {model_path} a TensorRT FP{precision}, imgsz={imgsz}, batch=1")
    print("El proceso puede tardar varios minutos y debe ejecutarse en la Jetson.")
    export_options = {
        "format": "engine",
        "device": system.get("device", 0),
        "imgsz": imgsz,
        "batch": 1,
        "dynamic": False,
        "simplify": False,
        "workspace": args.workspace,
    }
    if not args.fp32:
        export_options["quantize"] = 16
        try:
            import onnx_graphsurgeon  # noqa: F401
        except ImportError as error:
            raise RuntimeError(
                "Faltan dependencias ModelOpt ONNX. Reconstruya la imagen con: "
                "sudo docker build --no-cache -t aeye-yolo:dev ."
            ) from error

    exported = YOLO(str(model_path)).export(**export_options)
    print(f"Engine creado: {exported}")
    print('Para usarlo configure "inference_backend": "tensorrt" en cameras.json')


if __name__ == "__main__":
    main()
