#!/usr/bin/env bash
set -euo pipefail

API_HOST="${AEYE_API_HOST:-0.0.0.0}"
API_PORT="${AEYE_API_PORT:-8000}"
VISION_PID=""
API_PID=""

stop_processes() {
  trap - TERM INT
  if [[ -n "$VISION_PID" ]]; then
    kill "$VISION_PID" 2>/dev/null || true
  fi
  if [[ -n "$API_PID" ]]; then
    kill "$API_PID" 2>/dev/null || true
  fi
  wait "$VISION_PID" "$API_PID" 2>/dev/null || true
}

trap stop_processes TERM INT EXIT

python3 main.py &
VISION_PID=$!

# main.py applies database migrations before loading the TensorRT engine.
sleep 2
if ! kill -0 "$VISION_PID" 2>/dev/null; then
  wait "$VISION_PID"
fi

python3 -m uvicorn api.app:app --host "$API_HOST" --port "$API_PORT" &
API_PID=$!

set +e
wait -n "$VISION_PID" "$API_PID"
STATUS=$?
set -e

exit "$STATUS"

