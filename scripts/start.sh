#!/usr/bin/env bash
# CENTBOT start script (Linux/macOS)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -f data/EMERGENCY_STOP ]]; then
  echo "[CENTBOT] Emergency stop is active. Remove data/EMERGENCY_STOP to start."
  exit 1
fi

mkdir -p data logs backups sandbox

if [[ -f data/centbot.pid ]]; then
  OLD_PID="$(cat data/centbot.pid)"
  if kill -0 "$OLD_PID" 2>/dev/null; then
    echo "[CENTBOT] Already running (PID $OLD_PID). Use scripts/stop.sh first."
    exit 1
  fi
  rm -f data/centbot.pid
fi

echo "[CENTBOT] Starting autonomous workstation..."
nohup python3 -m centbot --config config/default.yaml >> logs/stdout.log 2>&1 &
echo $! > data/centbot.pid
echo "[CENTBOT] Started PID $(cat data/centbot.pid). Dashboard: http://127.0.0.1:8787"
