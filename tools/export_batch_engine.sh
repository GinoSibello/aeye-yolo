#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

SOURCE_MODEL="${1:-yolov8n.pt}"
OUTPUT_ENGINE="${2:-yolov8n_batch8.engine}"
BATCH_SIZE="${3:-8}"
IMAGE_SIZE="${4:-640}"
IMAGE="${AEYE_IMAGE:-aeye-yolo:dev}"
TEMP_DIR="$(mktemp -d /tmp/aeye-engine.XXXXXX)"

cleanup() {
  rm -rf "$TEMP_DIR"
}
trap cleanup EXIT INT TERM

if ! [[ "$BATCH_SIZE" =~ ^[1-9][0-9]*$ ]]; then
  printf 'batch_size debe ser un entero positivo.\n' >&2
  exit 2
fi
if ! [[ "$IMAGE_SIZE" =~ ^[1-9][0-9]*$ ]]; then
  printf 'imgsz debe ser un entero positivo.\n' >&2
  exit 2
fi
if [[ ! -f "$SOURCE_MODEL" ]]; then
  printf 'No existe el modelo fuente: %s\n' "$SOURCE_MODEL" >&2
  exit 2
fi
if [[ -e "$OUTPUT_ENGINE" && "${AEYE_OVERWRITE_ENGINE:-0}" != "1" ]]; then
  printf 'El engine ya existe: %s\n' "$OUTPUT_ENGINE" >&2
  printf 'Usa AEYE_OVERWRITE_ENGINE=1 para reemplazarlo explicitamente.\n' >&2
  exit 2
fi
if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  printf 'No existe la imagen Docker: %s\n' "$IMAGE" >&2
  exit 3
fi

cp "$SOURCE_MODEL" "$TEMP_DIR/model.pt"

docker run --rm \
  --runtime=nvidia \
  --ipc=host \
  --ulimit memlock=-1 \
  --ulimit stack=67108864 \
  -e "BATCH_SIZE=$BATCH_SIZE" \
  -e "IMAGE_SIZE=$IMAGE_SIZE" \
  -v "$TEMP_DIR:/work" \
  -w /work \
  "$IMAGE" \
  bash -lc '
    python3 -m pip install --no-cache-dir "nvidia-modelopt[onnx]"
    python3 -c "
import os
from ultralytics import YOLO
YOLO(\"/work/model.pt\").export(
    format=\"engine\",
    imgsz=int(os.environ[\"IMAGE_SIZE\"]),
    batch=int(os.environ[\"BATCH_SIZE\"]),
    dynamic=True,
    quantize=16,
    workspace=2,
    device=0,
    simplify=False,
)
"
  '

docker run --rm \
  --runtime=nvidia \
  -v "$TEMP_DIR:/work:ro" \
  -w /work \
  "$IMAGE" \
  python3 -c '
import json
import struct
from pathlib import Path
import tensorrt as trt
data = Path("model.engine").read_bytes()
length = struct.unpack("<I", data[:4])[0]
metadata = json.loads(data[4:4 + length])
logger = trt.Logger(trt.Logger.ERROR)
with trt.Runtime(logger) as runtime:
    engine = runtime.deserialize_cuda_engine(data[4 + length:])
    profile = engine.get_tensor_profile_shape("images", 0)
print(f"metadata_batch={metadata['batch']} dynamic={metadata['args']['dynamic']}")
print(f"profile_min_opt_max={profile}")
'

mkdir -p "$(dirname -- "$OUTPUT_ENGINE")"
cp "$TEMP_DIR/model.engine" "$OUTPUT_ENGINE"
printf 'Engine batch creado: %s\n' "$OUTPUT_ENGINE"
