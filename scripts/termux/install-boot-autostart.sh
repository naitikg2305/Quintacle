#!/data/data/com.termux/files/usr/bin/bash
# Installs scripts/termux/boot-autostart.sh into ~/.termux/boot/, with this
# repo's actual on-device path filled in, so Termux:Boot will run it.
#
# This script only does the scriptable part (writing the file). It does NOT
# and CANNOT:
#   - install the Termux:Boot app itself (a separate app, from F-Droid/
#     Google Play; Termux's own package manager can't install other apps)
#   - launch Termux:Boot once by hand, which Android requires before it'll
#     be allowed to run anything at boot
#   - exempt Termux from battery optimization (an Android Settings toggle)
# All three are manual, one-time, physical-device steps — see
# docs/termux-backend-setup.md for exact instructions.
#
# Usage: bash scripts/termux/install-boot-autostart.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
BOOT_DIR="$HOME/.termux/boot"
DEST="$BOOT_DIR/start-quintacle"

mkdir -p "$BOOT_DIR"
sed "s|__QUINTACLE_REPO_ROOT__|$REPO_ROOT|" \
  "$SCRIPT_DIR/boot-autostart.sh" > "$DEST"
chmod +x "$DEST"

echo "Installed $DEST (repo root: $REPO_ROOT)"
echo
echo "Remaining MANUAL steps (can't be scripted from here):"
echo "  1. Install the 'Termux:Boot' app (same source as Termux itself —"
echo "     F-Droid recommended; the Play Store build of Termux is"
echo "     unmaintained and often incompatible)."
echo "  2. Open Termux:Boot once by hand (tap its launcher icon) — Android"
echo "     requires an app to have been opened at least once before it's"
echo "     allowed to receive the BOOT_COMPLETED broadcast."
echo "  3. In Android Settings, exempt Termux (and Termux:Boot) from battery"
echo "     optimization, and allow 'autostart'/'run in background' if your"
echo "     phone's OEM skin has that extra toggle (common on MIUI/ColorOS/"
echo "     OneUI — see docs/termux-backend-setup.md for the per-vendor menu"
echo "     names)."
echo "  4. Reboot the phone once to confirm it actually comes up — check"
echo "     \$HOME/.quintacle-logs/boot.log and backend.log."
