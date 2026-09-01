#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

DURATION_SECONDS="${1:-120}"
ENGINE="${2:-models/stage5/yolo26s_fp16_640x640.engine}"
IMAGE="${AEYE_IMAGE:-aeye-yolo:dev}"
SOURCE_CONFIG="${AEYE_CONFIG_FILE:-$PROJECT_DIR/cameras.json}"
TEMP_DIR="$(mktemp -d /tmp/aeye-stage5.XXXXXX)"
TEMP_CONFIG="$TEMP_DIR/cameras-stage5.json"

cleanup() {
  rm -rf "$TEMP_DIR"
}
trap cleanup EXIT INT TERM

if [[ ! -f "$PROJECT_DIR/$ENGINE" ]]; then
  printf 'No existe el engine candidato: %s\n' "$PROJECT_DIR/$ENGINE" >&2
  exit 2
fi

python3 - "$SOURCE_CONFIG" "$TEMP_CONFIG" "$ENGINE" <<'PY_CONFIG'
import json
import sys

source, destination, engine = sys.argv[1:]
with open(source, encoding="utf-8") as stream:
    config = json.load(stream)
system = config["system"]
system["tensorrt_engine"] = engine
system["imgsz"] = 640
system["batching"] = {
    "enabled": False,
    "max_batch_size": 1,
    "timeout_ms": 0,
}
capture = dict(system.get("capture", {}))
capture.update({"backend": "ffmpeg", "fallback_to_ffmpeg": True})
system["capture"] = capture
system["pipeline"] = {
    "copy_latest_frame": False,
    "result_transfer": "packed",
}
config["preview"]["enabled"] = False
with open(destination, "w", encoding="utf-8") as stream:
    json.dump(config, stream, indent=2)
    stream.write("\n")
PY_CONFIG

OUTPUT="$(
  AEYE_IMAGE="$IMAGE" \
  AEYE_CONFIG_FILE="$TEMP_CONFIG" \
  AEYE_BENCHMARK_NAME="stage5_operational_yolo26s_640" \
    tools/run_stage0_baseline.sh "$DURATION_SECONDS"
)"
printf '%s\n' "$OUTPUT"
RUN_DIR="${OUTPUT#Baseline completo: }"

python3 - "$RUN_DIR" "$ENGINE" <<'PY_VALIDATE'
import json
import sys
from pathlib import Path

directory, expected_engine = Path(sys.argv[1]), Path(sys.argv[2]).name
summary = json.loads(
    (directory / "performance_summary.json").read_text(encoding="utf-8")
)
configuration = summary["configuration"]
if configuration["engine"] != expected_engine:
    raise SystemExit(
        f"Engine inesperado: {configuration['engine']} != {expected_engine}"
    )
if configuration["imgsz"] != [640, 640]:
    raise SystemExit(f"Resolucion inesperada: {configuration['imgsz']}")
if configuration["batching_enabled"]:
    raise SystemExit("La validacion operativa exige batch secuencial")
if configuration["copy_latest_frame"]:
    raise SystemExit("La validacion operativa exige snapshot compartido")
if configuration["result_transfer"] != "packed":
    raise SystemExit("La validacion operativa exige resultado empaquetado")
if summary["aggregate"]["processing_errors"]:
    raise SystemExit("Se observaron errores de procesamiento")
print(
    "Etapa 5 operativa validada: "
    f"camaras={len(summary['cameras'])} engine={configuration['engine']}"
)
PY_VALIDATE

printf 'Validacion operativa completa: %s\n' "$RUN_DIR"
