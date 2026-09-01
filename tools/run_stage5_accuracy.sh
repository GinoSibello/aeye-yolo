#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

IMAGE="${AEYE_IMAGE:-aeye-yolo:dev}"
ENGINES_DIR="${AEYE_STAGE5_MODELS_DIR:-$PROJECT_DIR/models/stage5}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
OUTPUT_DIR="$PROJECT_DIR/benchmarks/stage5_$TIMESTAMP"
STATS_PID=""

cleanup() {
  if [[ -n "$STATS_PID" ]]; then
    kill "$STATS_PID" >/dev/null 2>&1 || true
    wait "$STATS_PID" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT INT TERM

if [[ ! -f "$PROJECT_DIR/datasets/coco/val2017.txt" ]]; then
  printf 'Falta COCO val. Ejecuta tools/prepare_coco_val.sh primero.\n' >&2
  exit 2
fi
mapfile -t ENGINES < <(find "$ENGINES_DIR" -maxdepth 1 -type f \
  -name 'yolo*_fp16_*.engine' | sort)
if [[ "${#ENGINES[@]}" -eq 0 ]]; then
  printf 'No hay engines FP16 de Etapa 5 en %s.\n' "$ENGINES_DIR" >&2
  exit 2
fi
if ! command -v tegrastats >/dev/null 2>&1; then
  printf 'No se encontro tegrastats.\n' >&2
  exit 3
fi
mkdir -p "$OUTPUT_DIR"

for ENGINE in "${ENGINES[@]}"; do
  NAME="$(basename -- "$ENGINE" .engine)"
  RUN_DIR="$OUTPUT_DIR/$NAME"
  mkdir -p "$RUN_DIR"
  printf '\n=== Etapa 5: %s sobre COCO val ===\n' "$NAME"
  tegrastats --interval 100 >"$RUN_DIR/tegrastats.log" 2>&1 &
  STATS_PID=$!
  set +e
  docker run --rm \
    --runtime=nvidia \
    --ipc=host \
    --ulimit memlock=-1 \
    --ulimit stack=67108864 \
    -v "$PROJECT_DIR:/workspace/aeye-yolo" \
    -w /workspace/aeye-yolo \
    -e YOLO_CONFIG_DIR=/tmp/Ultralytics \
    "$IMAGE" \
    python3 tools/evaluate_stage5.py \
      "/workspace/aeye-yolo/${ENGINE#"$PROJECT_DIR"/}" \
      --images-list /workspace/aeye-yolo/datasets/coco/val2017.txt \
      --output "/workspace/aeye-yolo/${RUN_DIR#"$PROJECT_DIR"/}/accuracy.json" \
      >"$RUN_DIR/evaluation.log" 2>&1
  STATUS=$?
  set -e
  kill "$STATS_PID" >/dev/null 2>&1 || true
  wait "$STATS_PID" >/dev/null 2>&1 || true
  STATS_PID=""
  python3 tools/summarize_tegrastats.py \
    "$RUN_DIR/tegrastats.log" \
    --output "$RUN_DIR/tegrastats_summary.json"
  if [[ "$STATUS" -ne 0 ]]; then
    tail -n 80 "$RUN_DIR/evaluation.log" >&2
    exit "$STATUS"
  fi
  python3 - "$RUN_DIR/accuracy.json" <<'PY_RESULT'
import json
import sys
row = json.load(open(sys.argv[1], encoding="utf-8"))
person = row["person_metrics"]
counting = row["counting"]
speed = row["speed_ms_per_image"]
print(
    f"mAP50-95={person['map50_95']:.4f} "
    f"P@0.1={row['operational_iou50']['precision']:.4f} "
    f"R@0.1={row['operational_iou50']['recall']:.4f} "
    f"count_MAE={counting['mae_people_per_image']:.3f} "
    f"inference_ms={speed['inference']:.3f}"
)
PY_RESULT
done

python3 tools/summarize_stage5.py "$OUTPUT_DIR" \
  --output "$OUTPUT_DIR/stage5_summary.json"
printf '\nEtapa 5 completa: %s\n' "$OUTPUT_DIR"
