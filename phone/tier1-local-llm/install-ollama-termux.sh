#!/data/data/com.termux/files/usr/bin/bash
# Quintacle — Tier 1: install and run Ollama inside Termux, so the KB chat's
# `local:` models (core/quintacle_core/nodes/kb/chat.py → _run_local) work
# fully on-device with zero core changes.
#
# Run this INSIDE Termux on the phone, AFTER scripts/termux/setup.sh (which
# installs curl, used below to wait for the daemon). Full ordered playbook:
# phone/tier1-local-llm/README.md.
#
# Usage:
#   bash phone/tier1-local-llm/install-ollama-termux.sh
#       install ollama via pkg, disk-space check, start the daemon,
#       pull the default model (qwen2.5:1.5b, ~1 GB)
#   bash phone/tier1-local-llm/install-ollama-termux.sh --model llama3.2:1b
#       smaller/faster model (~0.8 GB); --model is repeatable
#   bash phone/tier1-local-llm/install-ollama-termux.sh --model qwen3:4b
#       the step-up model (~2.5 GB) — fine on the 12 GB-RAM S25U
#       (docs/on-device-s25u.md), skip on lower-RAM phones
#   bash phone/tier1-local-llm/install-ollama-termux.sh --serve
#       no install steps: run `ollama serve` in the foreground under
#       termux-wake-lock with a restart-on-crash loop (mirrors
#       scripts/termux/start-backend.sh). This is what the Termux:Boot
#       snippet (phone/tier1-local-llm/boot-ollama) launches detached.
#   --skip-disk-check   bypass the free-space guard (e.g. after freeing
#                       space mid-run, or if df misreads your setup)
#
# Loopback only: ollama's default bind is 127.0.0.1:11434 (we don't set
# OLLAMA_HOST), matching the backend's own 127.0.0.1-only uvicorn bind and
# quintacle-phone-env.sh's QUINTACLE_OLLAMA_HOST. Nothing is exposed to the
# network.
#
# Safe to re-run; pkg install and ollama pull both skip what's already there.
#
# Honesty note: this script has been bash -n checked and its ollama
# invocations (serve / pull / list / ps) verified against a real ollama CLI
# on desktop Linux, but it has NOT yet been executed on an actual Android
# device. `pkg install ollama` availability was confirmed against the Termux
# main repo package pool (ollama 0.40.3, aarch64) on 2026-10-15 — see
# phone/tier1-local-llm/README.md for the full verified-vs-pending list.

set -uo pipefail  # no -e: the --serve restart loop must survive a crash;
                  # install-path failures are checked explicitly instead.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_PATH="$SCRIPT_DIR/$(basename "${BASH_SOURCE[0]}")"
LOG_DIR="$HOME/.quintacle-logs"   # same log home as scripts/termux/boot-autostart.sh

OLLAMA_URL="http://127.0.0.1:11434"
DEFAULT_MODEL="qwen2.5:1.5b"
# Models land under ~/.ollama; the pull also needs scratch headroom, so ask
# for 4 GiB free to cover the default ~1 GB model (or ~2.5 GB for qwen3:4b)
# comfortably. Override with --skip-disk-check if you know better.
MIN_FREE_KB=$((4 * 1024 * 1024))

MODELS=()
SERVE_ONLY=0
SKIP_DISK_CHECK=0

while [ $# -gt 0 ]; do
  case "$1" in
    --serve) SERVE_ONLY=1 ;;
    --skip-disk-check) SKIP_DISK_CHECK=1 ;;
    --model)
      if [ $# -lt 2 ]; then
        echo "!! --model needs an argument (e.g. --model llama3.2:1b)" >&2
        exit 1
      fi
      MODELS+=("$2")
      shift
      ;;
    -h|--help)
      sed -n '2,39p' "$SCRIPT_PATH"   # print the header comment as help
      exit 0
      ;;
    *)
      echo "!! Unknown argument: $1 (try --help)" >&2
      exit 1
      ;;
  esac
  shift
done
if [ ${#MODELS[@]} -eq 0 ]; then
  MODELS=("$DEFAULT_MODEL")
fi

if [ -z "${PREFIX:-}" ] || [ ! -d "${PREFIX:-/nonexistent}" ]; then
  echo "!! \$PREFIX is not set to a Termux install — this script is Termux-only"
  echo "!! (it calls 'pkg', which only exists inside Termux). Aborting."
  exit 1
fi

serve_loop() {
  if ! command -v ollama >/dev/null 2>&1; then
    echo "!! ollama is not installed — run this script without --serve first" >&2
    exit 1
  fi
  # Keep the CPU from sleeping while the daemon is meant to be reachable —
  # same quick, non-blocking call start-backend.sh makes for uvicorn. Note
  # a held wake lock means the CPU never deep-sleeps; see the battery notes
  # in phone/tier1-local-llm/README.md.
  if command -v termux-wake-lock >/dev/null 2>&1; then
    termux-wake-lock
  else
    echo "!! termux-wake-lock not found — install the Termux:API app and"
    echo "!! 'pkg install termux-api' for this to work (see docs/termux-backend-setup.md)."
  fi
  echo "Starting ollama serve on $OLLAMA_URL with restart-on-crash ..."
  while true; do
    ollama serve
    EXIT_CODE=$?
    echo "$(date -Iseconds) ollama serve exited with code $EXIT_CODE — restarting in 5s" >&2
    sleep 5
  done
}

if [ "$SERVE_ONLY" = 1 ]; then
  serve_loop   # never returns
fi

echo "== 1/4: disk-space check (models are ~1-3 GB) =="
# Models are stored under ~/.ollama, so measure $HOME's filesystem.
AVAIL_KB="$(df -Pk "$HOME" | awk 'NR==2 {print $4}')"
if [ "$SKIP_DISK_CHECK" = 1 ]; then
  echo "   skipped (--skip-disk-check); ${AVAIL_KB:-?} KB available on \$HOME"
elif [ -z "$AVAIL_KB" ]; then
  echo "!! Couldn't read free space for $HOME via df — re-run with"
  echo "!! --skip-disk-check if you're sure there's >= 4 GiB free."
  exit 1
elif [ "$AVAIL_KB" -lt "$MIN_FREE_KB" ]; then
  echo "!! Only $((AVAIL_KB / 1024)) MB free on \$HOME's filesystem; want >= $((MIN_FREE_KB / 1024)) MB."
  echo "!! Free up space (or pick the smaller llama3.2:1b model AND pass"
  echo "!! --skip-disk-check if you've done the math) and re-run."
  exit 1
else
  echo "   ok: $((AVAIL_KB / 1024)) MB free"
fi

echo "== 2/4: installing ollama via pkg =="
if ! pkg install -y ollama; then
  echo
  echo "!! 'pkg install ollama' failed. The package is in the Termux main"
  echo "!! repo (confirmed 2026-10-15), so try, in order:"
  echo "!!   1. pkg update -y && pkg install -y ollama"
  echo "!!   2. pkg search ollama   (check the name on your Termux version)"
  echo "!! See phone/tier1-local-llm/README.md for the fallback story."
  exit 1
fi

echo "== 3/4: starting the ollama daemon =="
if curl -sf --max-time 2 "$OLLAMA_URL/api/version" >/dev/null 2>&1; then
  echo "   already running at $OLLAMA_URL"
else
  mkdir -p "$LOG_DIR"
  # Launch our own --serve mode (wake lock + restart loop) detached, same
  # nohup+disown pattern as scripts/termux/boot-autostart.sh.
  nohup bash "$SCRIPT_PATH" --serve >> "$LOG_DIR/ollama.log" 2>&1 &
  disown
  echo "   launched serve loop (pid $!, log: $LOG_DIR/ollama.log); waiting for the API ..."
  ATTEMPTS=0
  until curl -sf --max-time 2 "$OLLAMA_URL/api/version" >/dev/null 2>&1; do
    ATTEMPTS=$((ATTEMPTS + 1))
    if [ "$ATTEMPTS" -ge 30 ]; then
      echo "!! ollama didn't answer at $OLLAMA_URL within 30s — check $LOG_DIR/ollama.log"
      exit 1
    fi
    sleep 1
  done
  echo "   up."
fi

echo "== 4/4: pulling model(s): ${MODELS[*]} =="
for MODEL in "${MODELS[@]}"; do
  # `ollama pull` is idempotent (re-verifies and no-ops if current) and
  # resumes partial downloads, so a dropped connection just means re-running.
  if ! ollama pull "$MODEL"; then
    echo "!! 'ollama pull $MODEL' failed — flaky network and low disk are the"
    echo "!! usual causes; re-run this script to resume the download."
    exit 1
  fi
done

echo
echo "Installed models:"
ollama list
echo
echo "Done. Next steps:"
echo "  1. (Re)start the backend: bash scripts/termux/start-backend.sh"
echo "     — it auto-sources phone/tier1-local-llm/quintacle-phone-env.sh,"
echo "     pointing the app at this daemon."
echo "  2. In the chat's model picker choose 'local:${MODELS[0]}'"
echo "     (any pulled model works as 'local:<name>')."
echo "  3. Make ollama survive reboots: see 'Boot persistence' in"
echo "     phone/tier1-local-llm/README.md (the boot-ollama snippet)."
echo "  4. Sanity checks any time: 'ollama ps' (what's loaded in RAM),"
echo "     'ollama list' (what's on disk), 'curl $OLLAMA_URL/api/version'."
