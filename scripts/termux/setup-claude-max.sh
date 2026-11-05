#!/data/data/com.termux/files/usr/bin/bash
# Quintacle — OPTIONAL, best-effort: Claude Max (subscription) on the phone
# (2026-11-05).
#
# !! UNTESTED. Never run on a device. If any step fails, nothing breaks:
# !! max_backend.py only uses Max when a `claude` binary is on PATH and a
# !! call through it succeeds — otherwise every cloud call goes straight to
# !! the ANTHROPIC_API_KEY in core/.env, exactly as without this script.
#
# Why proot: Claude Code ships glibc Linux builds; Termux is bionic libc.
# proot-distro (Termux main repo) gives an Ubuntu userland where the normal
# installer works. A tiny `claude` wrapper on Termux's PATH then forwards
# into it, so max_backend.py finds it with no code change.
#
# Run INSIDE Termux:
#   bash scripts/termux/setup-claude-max.sh           # install + wrapper
#   bash scripts/termux/setup-claude-max.sh --remove  # drop the wrapper (back to API-only)
#
# After it finishes, log in ONCE, interactively (opens a URL to approve):
#   claude            # inside the session type /login, pick the Max account, then /exit
# Then restart the backend (bash scripts/termux/update.sh).

set -euo pipefail

DISTRO="ubuntu"
WRAPPER="${PREFIX:-}/bin/claude"
INNER_BIN="/root/.local/bin/claude"   # where the native installer puts it

if [ -z "${PREFIX:-}" ] || [ ! -d "${PREFIX:-/nonexistent}" ]; then
  echo "!! \$PREFIX is not set to a Termux install — this script is Termux-only. Aborting."
  exit 1
fi

if [ "${1:-}" = "--remove" ]; then
  rm -f "$WRAPPER"
  echo "Removed $WRAPPER — Quintacle's cloud calls now go straight to the API."
  exit 0
fi

echo "== 1/4: proot-distro =="
pkg install -y proot-distro

echo "== 2/4: Ubuntu userland (skipped if already installed) =="
if proot-distro login "$DISTRO" -- true >/dev/null 2>&1; then
  echo "   $DISTRO already installed"
else
  proot-distro install "$DISTRO"
fi

echo "== 3/4: Claude Code inside $DISTRO =="
proot-distro login "$DISTRO" -- bash -lc '
  set -e
  if [ -x /root/.local/bin/claude ]; then
    echo "   already installed: $(/root/.local/bin/claude --version 2>/dev/null || echo ?)"
    exit 0
  fi
  apt-get update -y
  apt-get install -y curl ca-certificates
  curl -fsSL https://claude.ai/install.sh | bash
'

echo "== 4/4: wrapper at $WRAPPER =="
cat > "$WRAPPER" <<EOF
#!/data/data/com.termux/files/usr/bin/bash
# Quintacle: forwards to Claude Code inside proot-distro $DISTRO
# (scripts/termux/setup-claude-max.sh). Remove with --remove to go API-only.
exec proot-distro login $DISTRO -- $INNER_BIN "\$@"
EOF
chmod +x "$WRAPPER"

if "$WRAPPER" --version >/dev/null 2>&1; then
  echo "   ok: $("$WRAPPER" --version)"
else
  echo "!! The wrapper doesn't run Claude Code yet — check the install output"
  echo "!! above. Quintacle keeps using the API meanwhile. To undo: $0 --remove"
  exit 1
fi

echo
echo "Next (once): run 'claude', type /login, sign in with the Max account, /exit."
echo "Then: bash scripts/termux/update.sh  (restarts the backend so it picks Max up)."
echo "Check: pick a max:* model in chat — if the reply carries the 'fell back to"
echo "the API' note, Max isn't working (not logged in?) and the API answered."
