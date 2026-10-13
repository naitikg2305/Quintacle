#!/data/data/com.termux/files/usr/bin/bash
# Quintacle — data migration, step 2 of 2: run INSIDE Termux on the phone.
#
# Unpacks a tarball produced by migrate-export.sh (run on the desktop) into
# the on-device data directory. Defaults to the same path
# start-backend.sh/setup.sh expect: $QUINTACLE_DATA_DIR or ~/.quintacle,
# kept in Termux's own private home (NOT Android shared storage — see the
# SQLite-over-FUSE note in start-backend.sh).
#
# Usage:
#   bash scripts/termux/migrate-import.sh /path/to/quintacle-data-*.tar.gz [DEST_DIR]
#
#   DEST_DIR defaults to $QUINTACLE_DATA_DIR or ~/.quintacle
#
# Safety: if DEST_DIR already exists and is non-empty (e.g. you've already
# run the backend on-device and it created some files), this will NOT
# silently overwrite it — it moves the existing directory aside to
# DEST_DIR.bak-<timestamp> first. This script does not attempt to merge the
# two; if you need a merge, do it by hand (diff the two directories) before
# deleting the .bak copy.

set -euo pipefail

TARBALL="${1:?Usage: migrate-import.sh <tarball> [dest_dir]}"
DEST_DIR="${2:-${QUINTACLE_DATA_DIR:-$HOME/.quintacle}}"

if [ ! -f "$TARBALL" ]; then
  echo "!! Tarball not found: $TARBALL" >&2
  exit 1
fi

if [ -d "$DEST_DIR" ] && [ -n "$(ls -A "$DEST_DIR" 2>/dev/null)" ]; then
  BACKUP="$DEST_DIR.bak-$(date +%Y%m%d-%H%M%S)"
  echo "!! $DEST_DIR already exists and is non-empty."
  echo "!! Moving it aside to $BACKUP before importing (not merged automatically)."
  mv "$DEST_DIR" "$BACKUP"
fi

mkdir -p "$DEST_DIR"
echo "Unpacking $TARBALL -> $DEST_DIR ..."
# --strip-components=1 drops the tarball's fixed top-level "quintacle-data/"
# directory (written by migrate-export.sh) so DEST_DIR itself becomes the
# data root, not DEST_DIR/quintacle-data.
tar -xzf "$TARBALL" -C "$DEST_DIR" --strip-components=1

echo
echo "Done. Contents of $DEST_DIR:"
ls -la "$DEST_DIR"
echo
echo "Start the backend against this data with:"
echo "  QUINTACLE_DATA_DIR=$DEST_DIR bash scripts/termux/start-backend.sh --once"
