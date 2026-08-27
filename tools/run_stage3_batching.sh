#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

DURATION_SECONDS="${1:-120}"
IMAGE="${AEYE_IMAGE:-aeye-yolo:dev}"
SOURCE_CONFIG="${AEYE_CONFIG_FILE:-$PROJECT_DIR/cameras.json}"
SEQUENTIAL_ENGINE="${AEYE_SEQUENTIAL_ENGINE:-yolov8n.engine}"
BATCH_ENGINE="${AEYE_BATCH_ENGINE:-yolov8n_batch8.engine}"
BATCH_SIZE="${AEYE_BATCH_SIZE:-8}"
BATCH_TIMEOUT_MS="${AEYE_BATCH_TIMEOUT_MS:-10}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
SUMMARY_DIR="$PROJECT_DIR/benchmarks/stage3_$TIMESTAMP"
TEMP_DIR="$(mktemp -d /tmp/aeye-stage3.XXXXXX)"
RUN_DIRS=()

cleanup() {
  rm -rf "$TEMP_DIR"
}
trap cleanup EXIT INT TERM

for ENGINE in "$SEQUENTIAL_ENGINE" "$BATCH_ENGINE"; do
  if [[ ! -f "$PROJECT_DIR/$ENGINE" ]]; then
    printf 'No existe el engine requerido: %s\n' "$PROJECT_DIR/$ENGINE" >&2
    exit 2
  fi
done

mkdir -p "$SUMMARY_DIR"

for MODE in sequential batching; do
  TEMP_CONFIG="$TEMP_DIR/cameras-${MODE}.json"
  python3 - \
    "$SOURCE_CONFIG" "$TEMP_CONFIG" "$MODE" \
    "$SEQUENTIAL_ENGINE" "$BATCH_ENGINE" \
    "$BATCH_SIZE" "$BATCH_TIMEOUT_MS" <<'PY'
import json
import sys

(
    source,
    destination,
    mode,
    sequential_engine,
    batch_engine,
    batch_size,
    timeout_ms,
) = sys.argv[1:]
with open(source, encoding="utf-8") as stream:
    config = json.load(stream)
system = config["system"]
capture = dict(system.get("capture", {}))
capture.update({"backend": "ffmpeg", "fallback_to_ffmpeg": True})
system["capture"] = capture
enabled = mode == "batching"
system["tensorrt_engine"] = batch_engine if enabled else sequential_engine
system["batching"] = {
    "enabled": enabled,
    "max_batch_size": int(batch_size) if enabled else 1,
    "timeout_ms": int(timeout_ms) if enabled else 0,
}
with open(destination, "w", encoding="utf-8") as stream:
    json.dump(config, stream, indent=2)
    stream.write("\n")
PY

  printf '\n=== Etapa 3: %s durante %ss ===\n' "$MODE" "$DURATION_SECONDS"
  OUTPUT="$(
    AEYE_IMAGE="$IMAGE" \
    AEYE_CONFIG_FILE="$TEMP_CONFIG" \
    AEYE_BENCHMARK_NAME="stage3_${MODE}" \
      tools/run_stage0_baseline.sh "$DURATION_SECONDS"
  )"
  printf '%s\n' "$OUTPUT"
  RUN_DIR="${OUTPUT#Baseline completo: }"
  RUN_DIRS+=("$RUN_DIR")

  python3 - "$RUN_DIR" "$MODE" <<'PY'
import json
import sys
from pathlib import Path

directory, expected = Path(sys.argv[1]), sys.argv[2]
summary = json.loads(
    (directory / "performance_summary.json").read_text(encoding="utf-8")
)
configuration = summary["configuration"]
actual = "batching" if configuration["batching_enabled"] else "sequential"
if actual != expected:
    raise SystemExit(f"Modo inesperado: solicitado={expected} observado={actual}")
backends = {
    row["stream"].get("capture_backend")
    for row in summary["cameras"].values()
}
if backends != {"ffmpeg"}:
    raise SystemExit("La comparacion de Etapa 3 exige captura FFmpeg en ambos brazos")
batch_avg = summary["batching"]["batch_size"]["avg"]
if expected == "batching" and (batch_avg is None or batch_avg <= 1):
    raise SystemExit("No se observaron lotes mayores que uno")
if summary["aggregate"]["processing_errors"]:
    raise SystemExit("Se observaron errores de procesamiento")
print(
    f"modo_validado={expected} camaras={len(summary['cameras'])} "
    f"batch_promedio={batch_avg}"
)
PY
done

python3 tools/summarize_stage3.py \
  "${RUN_DIRS[@]}" \
  --output "$SUMMARY_DIR/stage3_summary.json"

printf '\nEtapa 3 completa: %s\n' "$SUMMARY_DIR"
