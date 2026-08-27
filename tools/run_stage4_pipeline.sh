#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

DURATION_SECONDS="${1:-120}"
IMAGE="${AEYE_IMAGE:-aeye-yolo:dev}"
SOURCE_CONFIG="${AEYE_CONFIG_FILE:-$PROJECT_DIR/cameras.json}"
ENGINE="${AEYE_SEQUENTIAL_ENGINE:-yolov8n.engine}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
SUMMARY_DIR="$PROJECT_DIR/benchmarks/stage4_$TIMESTAMP"
TEMP_DIR="$(mktemp -d /tmp/aeye-stage4.XXXXXX)"
RUN_DIRS=()

cleanup() {
  rm -rf "$TEMP_DIR"
}
trap cleanup EXIT INT TERM

if [[ ! -f "$PROJECT_DIR/$ENGINE" ]]; then
  printf 'No existe el engine requerido: %s\n' "$PROJECT_DIR/$ENGINE" >&2
  exit 2
fi
mkdir -p "$SUMMARY_DIR"

for MODE in baseline shared_frame packed_results optimized; do
  TEMP_CONFIG="$TEMP_DIR/cameras-${MODE}.json"
  python3 - "$SOURCE_CONFIG" "$TEMP_CONFIG" "$MODE" "$ENGINE" <<'PY_CONFIG'
import json
import sys

source, destination, mode, engine = sys.argv[1:]
with open(source, encoding="utf-8") as stream:
    config = json.load(stream)
system = config["system"]
capture = dict(system.get("capture", {}))
capture.update({"backend": "ffmpeg", "fallback_to_ffmpeg": True})
system["capture"] = capture
system["tensorrt_engine"] = engine
system["batching"] = {
    "enabled": False,
    "max_batch_size": 1,
    "timeout_ms": 0,
}
settings = {
    "baseline": (True, "split"),
    "shared_frame": (False, "split"),
    "packed_results": (True, "packed"),
    "optimized": (False, "packed"),
}
copy_latest_frame, result_transfer = settings[mode]
system["pipeline"] = {
    "copy_latest_frame": copy_latest_frame,
    "result_transfer": result_transfer,
}
with open(destination, "w", encoding="utf-8") as stream:
    json.dump(config, stream, indent=2)
    stream.write("\n")
PY_CONFIG

  printf '\n=== Etapa 4: %s durante %ss ===\n' "$MODE" "$DURATION_SECONDS"
  OUTPUT="$(
    AEYE_IMAGE="$IMAGE" \
    AEYE_CONFIG_FILE="$TEMP_CONFIG" \
    AEYE_BENCHMARK_NAME="stage4_${MODE}" \
      tools/run_stage0_baseline.sh "$DURATION_SECONDS"
  )"
  printf '%s\n' "$OUTPUT"
  RUN_DIR="${OUTPUT#Baseline completo: }"
  RUN_DIRS+=("$RUN_DIR")

  python3 - "$RUN_DIR" "$MODE" <<'PY_VALIDATE'
import json
import sys
from pathlib import Path

directory, expected = Path(sys.argv[1]), sys.argv[2]
summary = json.loads(
    (directory / "performance_summary.json").read_text(encoding="utf-8")
)
configuration = summary["configuration"]
settings = {
    (True, "split"): "baseline",
    (False, "split"): "shared_frame",
    (True, "packed"): "packed_results",
    (False, "packed"): "optimized",
}
actual = settings[(
    configuration["copy_latest_frame"],
    configuration["result_transfer"],
)]
if actual != expected:
    raise SystemExit(f"Modo inesperado: solicitado={expected} observado={actual}")
if configuration["batching_enabled"]:
    raise SystemExit("La Etapa 4 exige la ruta secuencial en todos los brazos")
backends = {
    row["stream"].get("capture_backend")
    for row in summary["cameras"].values()
}
if backends != {"ffmpeg"}:
    raise SystemExit("La Etapa 4 exige captura FFmpeg en todos los brazos")
if summary["aggregate"]["processing_errors"]:
    raise SystemExit("Se observaron errores de procesamiento")
print(f"modo_validado={actual} camaras={len(summary['cameras'])}")
PY_VALIDATE
done

python3 tools/summarize_stage4.py \
  "${RUN_DIRS[@]}" \
  --output "$SUMMARY_DIR/stage4_summary.json"

printf '\nEtapa 4 completa: %s\n' "$SUMMARY_DIR"
