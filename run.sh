#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

SECRET_FILE="${AEYE_CAMERA_PASSWORD_FILE:-/etc/aeye/camera_password}"

if ! sudo test -f "$SECRET_FILE"; then
  echo "No se encontro el secreto: $SECRET_FILE" >&2
  echo "Crealo siguiendo las instrucciones de README.md." >&2
  exit 1
fi

sudo docker run --rm -it \
  --runtime=nvidia \
  --network host \
  --ipc=host \
  --ulimit memlock=-1 \
  --ulimit stack=67108864 \
  --mount "type=bind,src=$SECRET_FILE,dst=/run/secrets/camera_password,readonly" \
  -v "$PROJECT_DIR:/workspace/aeye-yolo" \
  -w /workspace/aeye-yolo \
  aeye-yolo:dev \
  bash tools/start_runtime.sh
