#!/data/data/com.termux/files/usr/bin/bash
# Quintacle — start the FastAPI backend inside Termux, bound to loopback
# only, with the env vars it needs.
#
# Usage:
#   bash scripts/termux/start-backend.sh            # restart-on-crash loop (for Termux:Boot)
#   bash scripts/termux/start-backend.sh --once      # run once, foreground, no restart loop (for manual testing)
#
# Env vars you can override (all have sane defaults for an on-device setup):
#   QUINTACLE_DATA_DIR   - where the markdown/SQLite data lives. Defaults to
#                          ~/.quintacle, same convention as the desktop
#                          build. Deliberately NOT under Android shared
#                          storage (~/storage/shared/...): that's a FUSE
#                          mount and the backend keeps a live SQLite file in
#                          this directory (core/quintacle_core/db.py) —
#                          SQLite over FUSE/scoped-storage is known to be
#                          flaky/slow on Android. Keep it in Termux's own
#                          private home.
#   QUINTACLE_PORT       - defaults to 8000, matching the Capacitor app's
#                          hardcoded http://localhost:8000 base URL.
#
# ANTHROPIC_API_KEY / OPENAI_API_KEY / QUINTACLE_LLM_MODEL /
# QUINTACLE_LLM_RESEARCH_MODEL are read from core/.env by the app itself
# (api.py calls load_dotenv() before anything touches os.environ) — this
# script does not need to export them itself, it just needs to run with cwd
# set to core/ so python-dotenv's default upward search finds that file.

set -uo pipefail  # no -e: the restart loop below needs to survive a crash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
CORE_DIR="$REPO_ROOT/core"
VENV_DIR="$CORE_DIR/.venv"

export QUINTACLE_DATA_DIR="${QUINTACLE_DATA_DIR:-$HOME/.quintacle}"
PORT="${QUINTACLE_PORT:-8000}"

# Tier 1 phone profile (local-LLM env knobs), if installed — see phone/tier1-local-llm/README.md.
# shellcheck disable=SC1091
[ -f "$REPO_ROOT/phone/tier1-local-llm/quintacle-phone-env.sh" ] && source "$REPO_ROOT/phone/tier1-local-llm/quintacle-phone-env.sh"

if [ ! -f "$CORE_DIR/.env" ]; then
  echo "!! $CORE_DIR/.env is missing (ANTHROPIC_API_KEY etc. won't be set)."
  echo "!! Copy it from .env.example and fill in your key:"
  echo "!!   cp $CORE_DIR/.env.example $CORE_DIR/.env"
fi

if [ ! -d "$VENV_DIR" ]; then
  echo "!! No venv at $VENV_DIR — run scripts/termux/setup.sh first."
  exit 1
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
cd "$CORE_DIR"

# Keep the CPU from sleeping while the server is meant to be reachable.
# termux-wake-lock is a quick command (sets a flag), not a foreground hold,
# so it's safe to call before exec'ing/looping uvicorn below.
if command -v termux-wake-lock >/dev/null 2>&1; then
  termux-wake-lock
else
  echo "!! termux-wake-lock not found — install the Termux:API package and"
  echo "!! 'pkg install termux-api' for this to work (see docs/termux-backend-setup.md)."
fi

run_once() {
  exec uvicorn quintacle_core.api:app --host 127.0.0.1 --port "$PORT"
}

if [ "${1:-}" = "--once" ]; then
  echo "Starting uvicorn once (no restart loop) on 127.0.0.1:$PORT ..."
  run_once
fi

echo "Starting uvicorn on 127.0.0.1:$PORT with restart-on-crash ..."
while true; do
  uvicorn quintacle_core.api:app --host 127.0.0.1 --port "$PORT"
  EXIT_CODE=$?
  echo "$(date -Iseconds) uvicorn exited with code $EXIT_CODE — restarting in 5s" >&2
  sleep 5
done
