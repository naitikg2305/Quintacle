#!/data/data/com.termux/files/usr/bin/bash
# Quintacle — update the on-phone backend in place (2026-11-05).
#
# Run INSIDE Termux, after scripts/termux/setup.sh has been run once:
#   bash scripts/termux/update.sh              # pull the current branch
#   bash scripts/termux/update.sh redone-UI    # pull (and switch to) a branch
#
# What it does, every step safe to re-run:
#   1. git pull --ff-only of the branch (refuses on local edits — never
#      stashes or discards anything)
#   2. pip install -r core/requirements.txt into core/.venv (same Pillow/opencv
#      filter as setup.sh: those come from pkg, not pip)
#   3. if Ollama is installed: make sure the daemon is up and the phone
#      models are pulled (only missing ones are downloaded)
#   4. restart the backend the way it normally runs: if the start-backend.sh
#      restart loop is alive, stop uvicorn and let the loop bring it back on
#      the new code; otherwise launch start-backend.sh detached (the same
#      nohup+disown pattern as the Termux:Boot entry)
#   5. wait for http://127.0.0.1:8000 to answer
#
# The UI lives in the APK, not here: a frontend change needs a new APK
# (cd frontend && npm run android:build, then gradle; docs/reference/android.md).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
CORE_DIR="$REPO_ROOT/core"
VENV_DIR="$CORE_DIR/.venv"
LOG_DIR="$HOME/.quintacle-logs"
PORT="${QUINTACLE_PORT:-8000}"
PHONE_MODELS=("qwen3:4b" "qwen2.5:1.5b")

if [ -z "${PREFIX:-}" ] || [ ! -d "${PREFIX:-/nonexistent}" ]; then
  echo "!! \$PREFIX is not set to a Termux install — this script is Termux-only. Aborting."
  exit 1
fi
if [ ! -d "$VENV_DIR" ]; then
  echo "!! No venv at $VENV_DIR — run scripts/termux/setup.sh first."
  exit 1
fi
command -v pkill >/dev/null 2>&1 || pkg install -y procps

cd "$REPO_ROOT"
echo "== 1/5: git pull =="
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  echo "!! Local changes in $REPO_ROOT — commit or discard them yourself, then re-run."
  git status --short --untracked-files=no
  exit 1
fi
BRANCH="${1:-$(git rev-parse --abbrev-ref HEAD)}"
git fetch origin "$BRANCH"
if [ "$(git rev-parse --abbrev-ref HEAD)" != "$BRANCH" ]; then
  git checkout "$BRANCH"
fi
git pull --ff-only origin "$BRANCH"
echo "   now at $(git log -1 --format='%h %s')"

echo "== 2/5: pip install -r core/requirements.txt =="
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
FILTERED_REQS="$(mktemp)"
grep -viE '^(Pillow|opencv-python-headless)\s*$' "$CORE_DIR/requirements.txt" > "$FILTERED_REQS"
pip install -q -r "$FILTERED_REQS"
rm -f "$FILTERED_REQS"

echo "== 3/5: local models (Ollama) =="
if command -v ollama >/dev/null 2>&1; then
  if ! curl -sf --max-time 2 http://127.0.0.1:11434/api/version >/dev/null 2>&1; then
    mkdir -p "$LOG_DIR"
    nohup bash "$REPO_ROOT/phone/tier1-local-llm/install-ollama-termux.sh" --serve \
      >> "$LOG_DIR/ollama.log" 2>&1 &
    disown
    for _ in $(seq 30); do
      curl -sf --max-time 2 http://127.0.0.1:11434/api/version >/dev/null 2>&1 && break
      sleep 1
    done
  fi
  for M in "${PHONE_MODELS[@]}"; do
    if ollama list 2>/dev/null | awk 'NR>1 {print $1}' | grep -qx "$M"; then
      echo "   have $M"
    else
      echo "   pulling $M ..."
      ollama pull "$M" || echo "!! pull of $M failed — re-run later to resume"
    fi
  done
else
  echo "   ollama not installed — skipping (bash phone/tier1-local-llm/install-ollama-termux.sh)"
fi

echo "== 4/5: restarting the backend =="
if pgrep -f "scripts/termux/start-backend.sh" >/dev/null 2>&1; then
  # The restart-on-crash loop is alive: stopping uvicorn makes it relaunch
  # (on the freshly pulled code) after its 5 s back-off.
  pkill -f "uvicorn quintacle_core.api:app" || true
  echo "   stopped uvicorn; the start-backend.sh loop restarts it"
else
  pkill -f "uvicorn quintacle_core.api:app" || true
  mkdir -p "$LOG_DIR"
  nohup bash "$SCRIPT_DIR/start-backend.sh" >> "$LOG_DIR/backend.log" 2>&1 &
  disown
  echo "   launched start-backend.sh (log: $LOG_DIR/backend.log)"
fi

echo "== 5/5: waiting for http://127.0.0.1:$PORT =="
for _ in $(seq 60); do
  if curl -sf --max-time 2 "http://127.0.0.1:$PORT/documents" >/dev/null 2>&1; then
    echo "   up. Done."
    exit 0
  fi
  sleep 1
done
echo "!! backend didn't answer within 60 s — check $LOG_DIR/backend.log"
exit 1
