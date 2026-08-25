#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

DURATION_SECONDS="${1:-120}"
IMAGE="${AEYE_IMAGE:-aeye-yolo:dev}"
SOURCE_CONFIG="${AEYE_CONFIG_FILE:-$PROJECT_DIR/cameras.json}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
SUMMARY_DIR="$PROJECT_DIR/benchmarks/stage2_$TIMESTAMP"
TEMP_DIR="$(mktemp -d /tmp/aeye-stage2.XXXXXX)"
RUN_DIRS=()

cleanup() {
  rm -rf "$TEMP_DIR"
}
trap cleanup EXIT INT TERM

mkdir -p "$SUMMARY_DIR"

for BACKEND in ffmpeg gstreamer_nvdec; do
  TEMP_CONFIG="$TEMP_DIR/cameras-${BACKEND}.json"
  python3 - "$SOURCE_CONFIG" "$TEMP_CONFIG" "$BACKEND" <<'PY'
import json
import sys

source, destination, backend = sys.argv[1:4]
with open(source, encoding="utf-8") as stream:
    config = json.load(stream)
capture = dict(config["system"].get("capture", {}))
capture.update(
    {
        "backend": backend,
        "fallback_to_ffmpeg": backend == "ffmpeg",
        "codec": capture.get("codec", "h265"),
        "rtsp_latency_ms": int(capture.get("rtsp_latency_ms", 200)),
        "read_timeout_ms": int(capture.get("read_timeout_ms", 15000)),
    }
)
config["system"]["capture"] = capture
with open(destination, "w", encoding="utf-8") as stream:
    json.dump(config, stream, indent=2)
    stream.write("\n")
PY

  printf '\n=== Etapa 2: captura %s durante %ss ===\n' \
    "$BACKEND" "$DURATION_SECONDS"
  OUTPUT="$(
    AEYE_IMAGE="$IMAGE" \
    AEYE_CONFIG_FILE="$TEMP_CONFIG" \
    AEYE_BENCHMARK_NAME="stage2_${BACKEND}" \
      tools/run_stage0_baseline.sh "$DURATION_SECONDS"
  )"
  printf '%s\n' "$OUTPUT"
  RUN_DIR="${OUTPUT#Baseline completo: }"
  RUN_DIRS+=("$RUN_DIR")

  python3 - "$RUN_DIR" "$BACKEND" <<'PY'
import json
import sys
from pathlib import Path

directory, expected = Path(sys.argv[1]), sys.argv[2]
summary = json.loads(
    (directory / "performance_summary.json").read_text(encoding="utf-8")
)
rows = list(summary["cameras"].values())
actual = {row["stream"].get("capture_backend") for row in rows}
if actual != {expected}:
    raise SystemExit(
        "Backend inesperado; solicitado="
        + expected
        + " observado="
        + ",".join(sorted(str(value) for value in actual))
    )
if expected == "gstreamer_nvdec" and not all(
    row["stream"].get("hardware_decode") is True for row in rows
):
    raise SystemExit("NVDEC no quedo confirmado en todas las camaras")
print(
    "backend_validado="
    + expected
    + " camaras="
    + str(len(rows))
)
PY
done

python3 tools/summarize_stage2.py \
  "${RUN_DIRS[@]}" \
  --output "$SUMMARY_DIR/stage2_summary.json"

printf '\nEtapa 2 completa: %s\n' "$SUMMARY_DIR"
