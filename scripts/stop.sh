#!/usr/bin/env bash
# CENTBOT stop script (Linux/macOS)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -f data/centbot.pid ]]; then
  PID="$(cat data/centbot.pid)"
  echo "[CENTBOT] Stopping PID $PID..."
  kill "$PID" 2>/dev/null || true
  for _ in 1 2 3 4 5; do
    if ! kill -0 "$PID" 2>/dev/null; then
      break
    fi
    sleep 1
  done
  if kill -0 "$PID" 2>/dev/null; then
    kill -9 "$PID" 2>/dev/null || true
  fi
  rm -f data/centbot.pid
  echo "[CENTBOT] Stopped."
else
  pkill -f "python3 -m centbot" 2>/dev/null || true
  echo "[CENTBOT] Stop request sent."
fi
