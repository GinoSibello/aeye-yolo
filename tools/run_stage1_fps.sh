#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

DURATION_SECONDS="${1:-120}"
SOURCE_CONFIG="${AEYE_CONFIG_FILE:-$PROJECT_DIR/cameras.json}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
SUMMARY_DIR="$PROJECT_DIR/benchmarks/stage1_$TIMESTAMP"
TEMP_DIR="$(mktemp -d /tmp/aeye-stage1.XXXXXX)"
RUN_DIRS=()

cleanup() {
  rm -rf "$TEMP_DIR"
}
trap cleanup EXIT INT TERM

mkdir -p "$SUMMARY_DIR"

for FPS in 2 4 6 8; do
  TEMP_CONFIG="$TEMP_DIR/cameras-${FPS}fps.json"
  python3 - "$SOURCE_CONFIG" "$TEMP_CONFIG" "$FPS" <<'PY'
import json
import sys

source, destination, fps = sys.argv[1], sys.argv[2], float(sys.argv[3])
with open(source, encoding="utf-8") as stream:
    config = json.load(stream)
config["system"]["inference_fps_per_camera"] = fps
with open(destination, "w", encoding="utf-8") as stream:
    json.dump(config, stream, indent=2)
    stream.write("\n")
PY

  printf '\n=== Etapa 1: %s FPS por camara durante %ss ===\n' \
    "$FPS" "$DURATION_SECONDS"
  OUTPUT="$(
    AEYE_CONFIG_FILE="$TEMP_CONFIG" \
    AEYE_BENCHMARK_NAME="stage1_fps${FPS}" \
      tools/run_stage0_baseline.sh "$DURATION_SECONDS"
  )"
  printf '%s\n' "$OUTPUT"
  RUN_DIRS+=("${OUTPUT#Baseline completo: }")
done

python3 tools/summarize_stage1.py \
  "${RUN_DIRS[@]}" \
  --output "$SUMMARY_DIR/stage1_summary.json"

printf '\nEtapa 1 completa: %s\n' "$SUMMARY_DIR"
