#!/data/data/com.termux/files/usr/bin/bash
# Quintacle — Termux:Boot entry point.
#
# This file is meant to be COPIED (or symlinked) to:
#   ~/.termux/boot/start-quintacle
#
# so the Termux:Boot companion app runs it automatically every time the
# phone boots. Termux:Boot is a separate app from Termux itself — see
# docs/termux-backend-setup.md for the (manual, can't be scripted) steps to
# install and enable it.
#
# This script intentionally backgrounds the actual server and returns
# quickly: Termux:Boot invokes every file under ~/.termux/boot/ in sorted
# order and doesn't guarantee it'll babysit a long-running foreground
# process forever, so start-backend.sh's restart loop is launched detached
# (nohup + disown) instead of exec'd in place.

REPO_ROOT="__QUINTACLE_REPO_ROOT__"   # see install note below
LOG_DIR="$HOME/.quintacle-logs"
mkdir -p "$LOG_DIR"

if [ "$REPO_ROOT" = "__QUINTACLE_REPO_ROOT__" ]; then
  echo "!! boot-autostart.sh was copied without filling in REPO_ROOT." \
    >> "$LOG_DIR/boot.log"
  echo "!! Edit ~/.termux/boot/start-quintacle and replace __QUINTACLE_REPO_ROOT__" \
    >> "$LOG_DIR/boot.log"
  echo "!! with the absolute path to your quintacle checkout (e.g. \$HOME/quintacle)." \
    >> "$LOG_DIR/boot.log"
  exit 1
fi

nohup bash "$REPO_ROOT/scripts/termux/start-backend.sh" \
  >> "$LOG_DIR/backend.log" 2>&1 &
disown

echo "$(date -Iseconds) launched start-backend.sh (pid $!)" >> "$LOG_DIR/boot.log"
