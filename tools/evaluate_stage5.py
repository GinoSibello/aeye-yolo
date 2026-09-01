#!/usr/bin/env python3
"""Evalua precision de persona, conteo y latencia de un engine TensorRT."""

import argparse
import json
import math
import statistics
import struct
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import torch
from ultralytics import YOLO
from ultralytics.engine.validator import BaseValidator
from ultralytics.utils.metrics import DetMetrics, box_iou
from ultralytics.utils.ops import xywh2xyxy


class OfficialMatcher:
    """Reutiliza el matching uno-a-uno del validador oficial."""

    match_predictions = BaseValidator.match_predictions

    def __init__(self):
        self.iouv = torch.linspace(0.5, 0.95, 10)


class PersonEvaluator:
    """Acumula AP oficial y error de conteo para la clase COCO persona."""

    def __init__(self, count_confidence):
        self.count_confidence = float(count_confidence)
        self.matcher = OfficialMatcher()
        self.metrics = DetMetrics(names={0: "person"})
        self.count_pairs = []
        self.operational_tp = 0
        self.operational_fp = 0
        self.operational_fn = 0

    def update(self, result, label_path):
        """Incorpora una imagen con predicciones y etiquetas YOLO normalizadas."""
        prediction = (
            result.boxes.data[:, :6].detach().cpu().numpy()
            if result.boxes is not None and len(result.boxes)
            else np.zeros((0, 6), dtype=np.float32)
        )
        prediction = prediction[prediction[:, 5] == 0]
        pred_boxes = torch.as_tensor(prediction[:, :4], dtype=torch.float32)
        pred_conf = prediction[:, 4].astype(np.float32, copy=False)
        pred_cls = prediction[:, 5].astype(np.float32, copy=False)

        labels = load_person_labels(label_path)
        target_cls = labels[:, 0].astype(np.float32, copy=False)
        target_boxes = normalized_xywh_to_xyxy(
            labels[:, 1:5],
            result.orig_shape,
        )
        if len(prediction) and len(labels):
            iou = box_iou(target_boxes, pred_boxes)
            correct = self.matcher.match_predictions(
                torch.as_tensor(pred_cls),
                torch.as_tensor(target_cls),
                iou,
            ).numpy()
        else:
            correct = np.zeros((len(prediction), 10), dtype=bool)

        operational = pred_conf >= self.count_confidence
        ground_truth_count = len(labels)
        predicted_count = int(np.count_nonzero(operational))
        tp50 = int(correct[operational, 0].sum()) if correct.size else 0
        self.count_pairs.append((ground_truth_count, predicted_count))
        self.operational_tp += tp50
        self.operational_fp += predicted_count - tp50
        self.operational_fn += ground_truth_count - tp50
        self.metrics.update_stats({
            "tp": correct,
            "target_cls": target_cls,
            "target_img": np.unique(target_cls),
            "conf": pred_conf,
            "pred_cls": pred_cls,
            "im_name": Path(result.path).name,
        })


def load_person_labels(path):
    """Carga solo clase 0 y tolera imagenes COCO sin objetos persona."""
    if not path.is_file() or not path.read_text(encoding="utf-8").strip():
        return np.zeros((0, 5), dtype=np.float32)
    rows = np.loadtxt(path, dtype=np.float32, ndmin=2)
    if rows.shape[1] != 5:
        raise ValueError(f"Etiqueta no rectangular o segmentada: {path}")
    return rows[rows[:, 0] == 0]


def normalized_xywh_to_xyxy(rows, image_shape):
    """Convierte verdad terreno normalizada a pixeles de la imagen original."""
    if not len(rows):
        return torch.zeros((0, 4), dtype=torch.float32)
    height, width = image_shape
    boxes = torch.as_tensor(rows, dtype=torch.float32)
    boxes[:, [0, 2]] *= width
    boxes[:, [1, 3]] *= height
    return xywh2xyxy(boxes)


def read_engine_metadata(path):
    """Obtiene forma, precision y modo desde el prefijo JSON del engine."""
    data = Path(path).read_bytes()
    length = struct.unpack("<I", data[:4])[0]
    metadata = json.loads(data[4:4 + length])
    export_args = metadata.get("args", {})
    quantize = export_args.get("quantize")
    return {
        "imgsz": [int(value) for value in metadata["imgsz"]],
        "batch": int(metadata.get("batch", export_args.get("batch", 1))),
        "dynamic": bool(export_args.get("dynamic", False)),
        "precision": {8: "int8", 16: "fp16", 32: "fp32"}.get(
            quantize,
            str(quantize),
        ),
        "end2end": bool(
            metadata.get("end2end", export_args.get("end2end", False))
        ),
    }


def resolve_images(images_list, maximum=None):
    """Resuelve el listado COCO relativo a su raiz y aplica limite de smoke."""
    root = images_list.parent
    lines = [
        line.strip() for line in images_list.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if maximum is not None:
        lines = lines[:maximum]
    paths = [Path(line) if Path(line).is_absolute() else root / line for line in lines]
    missing = [path for path in paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Faltan {len(missing)} imagenes; primera: {missing[0]}")
    return paths


def label_for_image(image_path, dataset_root):
    """Mapea `images/val2017` a `labels/val2017` sin heuristica de texto."""
    relative = image_path.relative_to(dataset_root)
    if relative.parts[0] != "images":
        raise ValueError(f"Ruta fuera de images/: {image_path}")
    return dataset_root / "labels" / Path(*relative.parts[1:]).with_suffix(".txt")


def safe_ratio(numerator, denominator):
    """Divide contadores y conserva ausencia cuando no hay denominador."""
    return numerator / denominator if denominator else None


def counting_summary(pairs):
    """Resume error de conteo por imagen a partir de verdad terreno."""
    errors = [predicted - expected for expected, predicted in pairs]
    absolute = [abs(error) for error in errors]
    squared = [error * error for error in errors]
    return {
        "images": len(pairs),
        "ground_truth_people": sum(expected for expected, _ in pairs),
        "predicted_people": sum(predicted for _, predicted in pairs),
        "mae_people_per_image": statistics.fmean(absolute),
        "rmse_people_per_image": math.sqrt(statistics.fmean(squared)),
        "mean_bias_people_per_image": statistics.fmean(errors),
        "exact_count_rate": safe_ratio(sum(error == 0 for error in errors), len(pairs)),
        "within_one_rate": safe_ratio(sum(error <= 1 for error in absolute), len(pairs)),
        "false_positive_empty_images": sum(
            expected == 0 and predicted > 0 for expected, predicted in pairs
        ),
        "missed_people_images": sum(
            expected > 0 and predicted == 0 for expected, predicted in pairs
        ),
    }


def main():
    """Predice con forma fija y calcula AP oficial sin `val` rectangular."""
    parser = argparse.ArgumentParser(description="Evaluar un engine de Etapa 5")
    parser.add_argument("engine", type=Path)
    parser.add_argument("--images-list", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--count-confidence", type=float, default=0.1)
    parser.add_argument("--max-images", type=int)
    args = parser.parse_args()

    metadata = read_engine_metadata(args.engine)
    if metadata["precision"] != "fp16":
        raise ValueError("Etapa 5 inicial admite solamente engines FP16")
    if metadata["batch"] != 1 or metadata["dynamic"]:
        raise ValueError("La comparacion requiere engines fijos batch 1")
    image_paths = resolve_images(args.images_list, args.max_images)
    dataset_root = args.images_list.parent
    evaluator = PersonEvaluator(args.count_confidence)
    model = YOLO(str(args.engine), task="detect")
    stage_times = {key: [] for key in ("preprocess", "inference", "postprocess")}
    started = time.perf_counter()
    for index, image_path in enumerate(image_paths, start=1):
        results = model.predict(
            source=str(image_path),
            stream=False,
            batch=1,
            imgsz=tuple(metadata["imgsz"]),
            rect=False,
            device=0,
            classes=[0],
            conf=0.001,
            verbose=False,
        )
        if len(results) != 1:
            raise RuntimeError(
                f"Se esperaba un resultado para {image_path}, llegaron {len(results)}"
            )
        result = results[0]
        evaluator.update(
            result,
            label_for_image(Path(result.path), dataset_root),
        )
        for key in stage_times:
            value = result.speed.get(key)
            if isinstance(value, (int, float)):
                stage_times[key].append(float(value))
        if index % 250 == 0 or index == len(image_paths):
            print(f"Procesadas {index}/{len(image_paths)} imagenes", flush=True)
    wall_seconds = time.perf_counter() - started
    evaluator.metrics.process(plot=False)
    class_ids = [int(value) for value in evaluator.metrics.box.ap_class_index]
    if 0 not in class_ids:
        raise RuntimeError("La evaluacion no devolvio la clase persona")
    position = class_ids.index(0)
    precision, recall, map50, map50_95 = evaluator.metrics.class_result(position)
    tp = evaluator.operational_tp
    fp = evaluator.operational_fp
    fn = evaluator.operational_fn
    speed = {
        key: statistics.fmean(values) if values else None
        for key, values in stage_times.items()
    }
    payload = {
        "schema_version": 1,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "engine": args.engine.name,
        "engine_metadata": metadata,
        "dataset": "COCO 2017 val",
        "images_list": str(args.images_list),
        "evaluation_scope": "person class only",
        "person_metrics": {
            "precision_best_f1": float(precision),
            "recall_best_f1": float(recall),
            "map50": float(map50),
            "map50_95": float(map50_95),
            "ground_truth_instances": int(evaluator.metrics.nt_per_class[0]),
        },
        "operational_iou50": {
            "confidence": args.count_confidence,
            "true_positives": tp,
            "false_positives": fp,
            "false_negatives": fn,
            "precision": safe_ratio(tp, tp + fp),
            "recall": safe_ratio(tp, tp + fn),
        },
        "counting": counting_summary(evaluator.count_pairs),
        "speed_ms_per_image": speed,
        "wall_seconds": wall_seconds,
        "wall_images_per_second": len(image_paths) / wall_seconds,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
