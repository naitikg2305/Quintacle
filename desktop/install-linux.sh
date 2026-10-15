#!/usr/bin/env bash
# Install the packaged Quintacle desktop app (and the dev launcher) into the
# user's local dirs. Run after building: core/.venv/bin/pyinstaller desktop/quintacle.spec
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$HERE")"
DIST="$REPO_ROOT/dist/quintacle"

APP_DIR="$HOME/.local/opt/quintacle"
BIN_DIR="$HOME/.local/bin"
APPS_DIR="$HOME/.local/share/applications"
mkdir -p "$BIN_DIR" "$APPS_DIR"

if [ -x "$DIST/quintacle" ]; then
  rm -rf "$APP_DIR"
  mkdir -p "$(dirname "$APP_DIR")"
  cp -r "$DIST" "$APP_DIR"
  ln -sf "$APP_DIR/quintacle" "$BIN_DIR/quintacle"
  sed "s|@QUINTACLE_BIN@|$APP_DIR/quintacle|" "$HERE/quintacle.desktop" \
    > "$APPS_DIR/quintacle.desktop"
  echo "installed packaged app -> $APP_DIR (launcher: Quintacle)"
else
  echo "note: no built binary at $DIST — skipping packaged app."
  echo "      build it with: core/.venv/bin/pyinstaller desktop/quintacle.spec"
fi

sed "s|@LAUNCH_DEV@|$HERE/launch-dev.sh|" "$HERE/quintacle-dev.desktop" \
  > "$APPS_DIR/quintacle-dev.desktop"
echo "installed dev launcher (launcher: Quintacle (dev))"

update-desktop-database "$APPS_DIR" 2>/dev/null || true
