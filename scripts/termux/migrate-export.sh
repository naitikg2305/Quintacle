#!/usr/bin/env bash
# Quintacle — data migration, step 1 of 2: run on the DESKTOP (wherever the
# real ~/.quintacle currently lives), NOT in Termux.
#
# Packs the existing data directory (markdown entries + the SQLite file +
# the KB's assets/ directory of photos/PDFs — see
# core/quintacle_core/nodes/kb/store.py) into a single tarball, under a
# fixed top-level directory name ("quintacle-data") so migrate-import.sh on
# the phone doesn't need to know or care what the source folder was
# literally called.
#
# Why a tarball instead of the LAN-sync mechanic in
# docs/deployment-and-privacy.md: that sync is designed for two ALREADY-
# RUNNING copies of the app diffing an existing shared file line-by-line
# (and is explicitly append-only-safe only, per that doc's own "open
# questions" section — it doesn't yet handle in-place edits/conflicts). It
# assumes both ends already have a data store to diff against. This is a
# one-time cold bootstrap, seeding a phone that has no backend running yet
# at all — a plain tar + transfer is simpler and has no edge cases to worry
# about for a single one-directional first copy.
#
# Usage:
#   scripts/termux/migrate-export.sh [SRC_DIR] [OUT_TARBALL]
#
#   SRC_DIR      defaults to $QUINTACLE_DATA_DIR or ~/.quintacle
#   OUT_TARBALL  defaults to ./quintacle-data-<date>.tar.gz in the cwd
#
# After this completes, see docs/termux-backend-setup.md for how to get the
# tarball onto the phone (adb push, or a quick LAN http.server + curl) and
# then run migrate-import.sh *inside Termux* to unpack it.

set -euo pipefail

SRC_DIR="${1:-${QUINTACLE_DATA_DIR:-$HOME/.quintacle}}"
OUT_TARBALL="${2:-./quintacle-data-$(date +%Y%m%d-%H%M%S).tar.gz}"

if [ ! -d "$SRC_DIR" ]; then
  echo "!! Source data directory not found: $SRC_DIR" >&2
  exit 1
fi

if ! tar --version 2>/dev/null | grep -qi gnu; then
  echo "!! This script uses GNU tar's --transform flag. Your 'tar' doesn't"
  echo "!! look like GNU tar (fine on this repo's dev machine — Arch Linux —"
  echo "!! but flagging in case you're running this somewhere else, e.g."
  echo "!! macOS's BSD tar). If it fails, rename $SRC_DIR to a temp dir named"
  echo "!! 'quintacle-data' and tar that instead." >&2
fi

echo "Packing $SRC_DIR -> $OUT_TARBALL ..."
du -sh "$SRC_DIR"
tar -C "$(dirname "$SRC_DIR")" \
  --transform "s|^$(basename "$SRC_DIR")|quintacle-data|" \
  -czf "$OUT_TARBALL" \
  "$(basename "$SRC_DIR")"

echo
echo "Done: $(du -h "$OUT_TARBALL" | cut -f1)  $OUT_TARBALL"
echo
echo "Next: get this file onto the phone, then inside Termux run:"
echo "  bash scripts/termux/migrate-import.sh /path/to/$(basename "$OUT_TARBALL")"
echo
echo "See docs/termux-backend-setup.md for transfer options (adb push vs. LAN)."
