#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

IMAGE="${AEYE_IMAGE:-aeye-yolo:dev}"
MODELS_DIR="${AEYE_STAGE5_MODELS_DIR:-$PROJECT_DIR/models/stage5}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
REPORT="${AEYE_STAGE5_EXPORT_REPORT:-$PROJECT_DIR/benchmarks/stage5_exports_$TIMESTAMP.json}"
OVERWRITE=()
if [[ "${AEYE_OVERWRITE_ENGINE:-0}" == "1" ]]; then
  OVERWRITE=(--overwrite)
fi

mkdir -p "$MODELS_DIR" "$(dirname -- "$REPORT")"

docker run --rm \
  --runtime=nvidia \
  --network host \
  --ipc=host \
  --ulimit memlock=-1 \
  --ulimit stack=67108864 \
  -v "$PROJECT_DIR:/workspace/aeye-yolo" \
  -v "$MODELS_DIR:/models" \
  -w /models \
  "$IMAGE" \
  bash -lc '
    python3 -m pip install --no-cache-dir "nvidia-modelopt[onnx]"
    python3 /workspace/aeye-yolo/tools/export_stage5_engines.py \
      --weights-dir /models \
      --output-dir /models \
      --report /workspace/aeye-yolo/'"${REPORT#"$PROJECT_DIR"/}"' \
      '"${OVERWRITE[*]}"'
    chown -R '"$(id -u):$(id -g)"' /models \
      /workspace/aeye-yolo/'"${REPORT#"$PROJECT_DIR"/}"'
  '

printf 'Exportacion Etapa 5 completa: %s\n' "$REPORT"
