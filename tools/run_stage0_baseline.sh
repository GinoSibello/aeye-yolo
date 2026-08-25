#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

DURATION_SECONDS="${1:-120}"
IMAGE="${AEYE_IMAGE:-aeye-yolo:dev}"
SECRET_FILE="${AEYE_CAMERA_PASSWORD_FILE:-/etc/aeye/camera_password}"
CONFIG_FILE="${AEYE_CONFIG_FILE:-$PROJECT_DIR/cameras.json}"
BENCHMARK_NAME="${AEYE_BENCHMARK_NAME:-stage0}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
OUTPUT_DIR="$PROJECT_DIR/benchmarks/${BENCHMARK_NAME}_$TIMESTAMP"
CONTAINER_NAME="aeye-stage0-${TIMESTAMP}-$$"
STATS_PID=""
RUN_PID=""

if ! [[ "$DURATION_SECONDS" =~ ^[0-9]+$ ]] || (( DURATION_SECONDS < 10 )); then
  printf 'La duracion debe ser un entero de al menos 10 segundos.\n' >&2
  exit 2
fi

if [[ ! -f "$CONFIG_FILE" ]]; then
  printf 'No existe el archivo de configuracion %s.\n' "$CONFIG_FILE" >&2
  exit 2
fi
CONFIG_FILE="$(realpath "$CONFIG_FILE")"

python3 -c '
import json
import sys
with open(sys.argv[1], encoding="utf-8") as stream:
    preview_enabled = bool(json.load(stream)["preview"].get("enabled", False))
if preview_enabled:
    sys.exit("El baseline exige preview.enabled=false")
' "$CONFIG_FILE"

DOCKER=()
if docker info >/dev/null 2>&1; then
  DOCKER=(docker)
elif sudo -n docker info >/dev/null 2>&1; then
  DOCKER=(sudo -n docker)
else
  printf '%s\n'     'No hay acceso no interactivo a Docker.'     'Ejecuta este script desde una terminal con sudo ya validado o concede acceso controlado a Docker.' >&2
  exit 3
fi

if ! command -v tegrastats >/dev/null 2>&1; then
  printf 'No se encontro tegrastats en PATH.\n' >&2
  exit 4
fi

if ! "${DOCKER[@]}" image inspect "$IMAGE" >/dev/null 2>&1; then
  printf 'No existe la imagen Docker %s. Construyela antes del baseline.\n' "$IMAGE" >&2
  exit 5
fi

mkdir -p "$OUTPUT_DIR"
CONTAINER_OUTPUT="/workspace/aeye-yolo/${OUTPUT_DIR#"$PROJECT_DIR/"}"

cleanup() {
  if [[ -n "$STATS_PID" ]]; then
    kill "$STATS_PID" >/dev/null 2>&1 || true
    wait "$STATS_PID" >/dev/null 2>&1 || true
  fi
  "${DOCKER[@]}" rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
  if [[ -n "$RUN_PID" ]]; then
    wait "$RUN_PID" >/dev/null 2>&1 || true
    RUN_PID=""
  fi
}
trap cleanup EXIT INT TERM

{
  printf 'captured_at=%s\n' "$(date --iso-8601=seconds)"
  printf 'duration_seconds=%s\n' "$DURATION_SECONDS"
  printf 'image=%s\n' "$IMAGE"
  uname -a
  if [[ -r /etc/nv_tegra_release ]]; then
    sed -n '1p' /etc/nv_tegra_release
  fi
  nvpmodel -q 2>&1
} >"$OUTPUT_DIR/host_runtime.txt"

"${DOCKER[@]}" run --rm   --runtime=nvidia   "$IMAGE"   python3 -c '
import cv2
print("opencv_version=" + cv2.__version__)
for line in cv2.getBuildInformation().splitlines():
    stripped = line.strip()
    if stripped.startswith("Video I/O:") or stripped.startswith("FFMPEG:") or stripped.startswith("GStreamer:"):
        print(stripped)
' >"$OUTPUT_DIR/container_opencv.txt"

"${DOCKER[@]}" run --rm --runtime=nvidia "$IMAGE" bash -lc '
if ! command -v gst-inspect-1.0 >/dev/null 2>&1; then
  echo "gstreamer=unavailable"
  exit 0
fi
gst-launch-1.0 --version | sed -n "1,2p"
for plugin in rtspsrc rtph265depay h265parse nvv4l2decoder nvvidconv appsink; do
  if gst-inspect-1.0 "$plugin" >/dev/null 2>&1; then
    printf "%s=available\n" "$plugin"
  else
    printf "%s=missing\n" "$plugin"
  fi
done
' >"$OUTPUT_DIR/container_gstreamer.txt" 2>&1

"${DOCKER[@]}" run --rm \
  --name "$CONTAINER_NAME" \
  --runtime=nvidia \
  --network host \
  --ipc=host \
  --ulimit memlock=-1 \
  --ulimit stack=67108864 \
  --mount \
    "type=bind,src=$SECRET_FILE,dst=/run/secrets/camera_password,readonly" \
  --mount \
    "type=bind,src=$CONFIG_FILE,dst=/run/aeye/cameras.json,readonly" \
  -v "$PROJECT_DIR:/workspace/aeye-yolo" \
  -w /workspace/aeye-yolo \
  -e "AEYE_LOG_DIR=$CONTAINER_OUTPUT/logs" \
  -e "AEYE_DB_PATH=$CONTAINER_OUTPUT/aeye.db" \
  -e "AEYE_PERFORMANCE_PATH=$CONTAINER_OUTPUT/performance_summary.json" \
  -e "AEYE_CONFIG=/run/aeye/cameras.json" \
  "$IMAGE" >"$OUTPUT_DIR/aeye.log" 2>&1 &
RUN_PID=$!

READY=false
for _ in {1..120}; do
  if grep -q "AEYE iniciado con" "$OUTPUT_DIR/aeye.log"; then
    READY=true
    break
  fi
  if ! kill -0 "$RUN_PID" >/dev/null 2>&1; then
    set +e
    wait "$RUN_PID"
    RUN_STATUS=$?
    set -e
    RUN_PID=""
    printf 'AEYE termino durante el arranque (estado %s). Revisa %s\n' \
      "$RUN_STATUS" "$OUTPUT_DIR/aeye.log" >&2
    exit "$RUN_STATUS"
  fi
  sleep 0.5
done

if [[ "$READY" != true ]]; then
  printf 'AEYE no completo el arranque dentro de 60 segundos.\n' >&2
  exit 7
fi

tegrastats --interval 100 >"$OUTPUT_DIR/tegrastats.log" 2>&1 &
STATS_PID=$!
sleep "$DURATION_SECONDS"
kill "$STATS_PID" >/dev/null 2>&1 || true
wait "$STATS_PID" >/dev/null 2>&1 || true
STATS_PID=""

if ! "${DOCKER[@]}" exec "$CONTAINER_NAME" bash -lc '
count=0
for descriptor in /proc/1/fd/*; do
  target="$(readlink "$descriptor" 2>/dev/null || true)"
  case "$target" in
    *v4l2-nvdec*) count=$((count + 1));;
  esac
done
printf "nvdec_device=/dev/v4l2-nvdec\nopen_descriptors=%s\n" "$count"
' >"$OUTPUT_DIR/capture_device_evidence.txt" 2>/dev/null; then
  printf 'nvdec_device=unavailable\nopen_descriptors=unknown\n' \
    >"$OUTPUT_DIR/capture_device_evidence.txt"
fi
"${DOCKER[@]}" kill --signal=INT "$CONTAINER_NAME" >/dev/null
set +e
wait "$RUN_PID"
RUN_STATUS=$?
set -e
RUN_PID=""

python3 tools/summarize_tegrastats.py \
  "$OUTPUT_DIR/tegrastats.log" \
  --output "$OUTPUT_DIR/tegrastats_summary.json"

if [[ "$RUN_STATUS" -ne 0 ]]; then
  printf 'AEYE termino despues del baseline (estado %s). Revisa %s\n' \
    "$RUN_STATUS" "$OUTPUT_DIR/aeye.log" >&2
  exit "$RUN_STATUS"
fi
if [[ ! -f "$OUTPUT_DIR/performance_summary.json" ]]; then
  printf 'No se genero performance_summary.json. Revisa %s\n'     "$OUTPUT_DIR/aeye.log" >&2
  exit 6
fi

printf 'Baseline completo: %s\n' "$OUTPUT_DIR"
