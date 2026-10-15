#!/usr/bin/env bash
# Quintacle interim desktop launcher — works today, zero packaging.
#
# Starts the FastAPI backend (if nothing Quintacle-shaped answers on :8000),
# starts or reuses the dev frontend on :3000, then opens a chromium app-mode
# window (one window, no tabs/omnibox). Daily driver until the packaged
# pywebview binary (desktop/app.py + quintacle.spec) matures.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_URL="http://127.0.0.1:8000"
FRONTEND_URL="http://localhost:3000"
LOG_DIR="$HOME/.quintacle/logs"
mkdir -p "$LOG_DIR"

probe() { curl -sf --max-time 2 "$1" >/dev/null 2>&1; }

# --- backend (reuse if a Quintacle answers on :8000) -------------------------
if probe "$BACKEND_URL/kb/folders"; then
  echo "backend: reusing server on :8000"
else
  PY="$REPO_ROOT/core/.venv/bin/python"
  [ -x "$PY" ] || PY="$(command -v python3)"
  echo "backend: starting (log: $LOG_DIR/backend.log)"
  (cd "$REPO_ROOT/core" &&
    nohup "$PY" -m uvicorn quintacle_core.api:app --host 127.0.0.1 --port 8000 \
      >"$LOG_DIR/backend.log" 2>&1 &)
  for _ in $(seq 1 50); do
    probe "$BACKEND_URL/kb/folders" && break
    sleep 0.2
  done
  probe "$BACKEND_URL/kb/folders" || { echo "backend failed to start — see $LOG_DIR/backend.log"; exit 1; }
fi

# --- dev frontend (reuse if :3000 answers) ------------------------------------
if probe "$FRONTEND_URL"; then
  echo "frontend: reusing dev server on :3000"
else
  echo "frontend: starting npm run dev (log: $LOG_DIR/frontend-dev.log)"
  (cd "$REPO_ROOT/frontend" &&
    nohup npm run dev >"$LOG_DIR/frontend-dev.log" 2>&1 &)
  for _ in $(seq 1 150); do
    probe "$FRONTEND_URL" && break
    sleep 0.4
  done
  probe "$FRONTEND_URL" || { echo "frontend failed to start — see $LOG_DIR/frontend-dev.log"; exit 1; }
fi

# --- window --------------------------------------------------------------------
if command -v chromium >/dev/null 2>&1; then
  BROWSER_BIN=chromium
elif command -v google-chrome-stable >/dev/null 2>&1; then
  BROWSER_BIN=google-chrome-stable
else
  echo "no chromium/google-chrome-stable found; open $FRONTEND_URL yourself"
  exit 1
fi
exec "$BROWSER_BIN" --app="$FRONTEND_URL"
