"""Mide la latencia del engine TensorRT después del warmup."""

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

import cv2

# Al ejecutar `python3 tools/benchmark_detector.py`, Python agrega `tools/`
# al path, pero no necesariamente la raíz que contiene `vision/`.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from vision.detector import detect, load_detector


def main():
    """Carga entradas, ejecuta warmup y reporta latencia y detecciones."""
    parser = argparse.ArgumentParser(description="Benchmark de inferencia AEYE")
    parser.add_argument("input", help="Una imagen JPEG/PNG o una carpeta de imágenes")
    parser.add_argument("--runs", type=int, default=100)
    parser.add_argument("--warmup", type=int, default=10)
    parser.add_argument("--config", default="cameras.json")
    args = parser.parse_args()
    if args.runs < 1 or args.warmup < 0:
        raise ValueError("runs debe ser >= 1 y warmup >= 0")

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))["system"]
    input_path = Path(args.input)
    if input_path.is_dir():
        paths = sorted(
            path for path in input_path.iterdir()
            if path.suffix.lower() in {".jpg", ".jpeg", ".png"}
        )
    else:
        paths = [input_path]
    if not paths:
        raise FileNotFoundError(f"No se encontraron imágenes en: {input_path}")

    frames = []
    for path in paths:
        frame = cv2.imread(str(path))
        if frame is None:
            print(f"ADVERTENCIA: se omite una imagen ilegible: {path}")
            continue
        frames.append((path, frame))
    if not frames:
        raise RuntimeError("Ninguna imagen pudo ser leída por OpenCV")

    model = load_detector(cfg)
    for index in range(args.warmup):
        detect(model, frames[index % len(frames)][1], cfg)

    elapsed = []
    detections = []
    for path, frame in frames:
        image_counts = []
        for _ in range(args.runs):
            started = time.perf_counter()
            boxes = detect(model, frame, cfg)
            elapsed.append((time.perf_counter() - started) * 1000)
            image_counts.append(len(boxes))
        detections.append((path.name, image_counts[-1]))

    ordered = sorted(elapsed)
    p95 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]
    mean = statistics.mean(elapsed)
    print(f"backend=tensorrt images={len(frames)} runs_per_image={args.runs} total_runs={len(elapsed)}")
    print(f"detections_last_run={dict(detections)}")
    print(f"mean_ms={mean:.2f} p95_ms={p95:.2f} min_ms={min(elapsed):.2f}")
    print(f"theoretical_fps={1000.0 / mean:.2f}")


if __name__ == "__main__":
    main()
