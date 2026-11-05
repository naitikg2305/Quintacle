#!/data/data/com.termux/files/usr/bin/bash
# Quintacle — on-phone perception (Tier 2 TFLite lane): YOLOX-nano object
# tags, SCRFD face detect, ArcFace face embed (2026-11-05).
#
# UNTESTED ON A DEVICE. Written and bash -n checked on desktop; package names
# checked against the Termux main repo index on 2026-11-05
# (python-tflite-runtime 2.21.0, python-numpy 2.5.4, python-pillow 13.0.0).
#
# Run INSIDE Termux after scripts/termux/setup.sh:
#   bash scripts/termux/setup-perception.sh
#       models already in the data dir (they come along in the
#       migrate-export tarball — perception/models/tflite/)
#   bash scripts/termux/setup-perception.sh /path/to/tflite-dir
#       copy the *.tflite files from a folder you transferred yourself
#       (e.g. ~/storage/downloads/tflite — desktop source:
#       ~/.quintacle/perception/models/tflite/)
#
# Idempotent: pkg/pip skip what's there; model files are only copied when
# missing or different. Face enrollments (perception/profiles.json +
# embeddings/) also live in the data dir and come with the data migration —
# a face enrolled on the desktop is matched on the phone (parity-proven,
# phone/tier2-perception-tflite/README.md).
#
# The backend picks the lane up from phone/tier1-local-llm/quintacle-phone-env.sh
# (QUINTACLE_PERCEPTION_BACKEND=tflite, QUINTACLE_TFLITE_VARIANT=
# dynamic_range_quant), which start-backend.sh sources. If anything here
# fails, perceive_photo() returns None with one warning — drops still work.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
CORE_DIR="$REPO_ROOT/core"
VENV_DIR="$CORE_DIR/.venv"
DATA_DIR="${QUINTACLE_DATA_DIR:-$HOME/.quintacle}"
DEST="$DATA_DIR/perception/models/tflite"
SRC="${1:-}"
MODELS=(yolox_nano det_500m w600k_mbf)
VARIANT="${QUINTACLE_TFLITE_VARIANT:-dynamic_range_quant}"

if [ -z "${PREFIX:-}" ] || [ ! -d "${PREFIX:-/nonexistent}" ]; then
  echo "!! \$PREFIX is not set to a Termux install — this script is Termux-only. Aborting."
  exit 1
fi
if [ ! -d "$VENV_DIR" ]; then
  echo "!! No venv at $VENV_DIR — run scripts/termux/setup.sh first."
  exit 1
fi

echo "== 1/4: LiteRT runtime + numpy + Pillow (Termux pkg builds) =="
# ai-edge-litert (the desktop runtime) has only glibc wheels; Termux's own
# python-tflite-runtime is the bionic build with the same Interpreter API
# (backend_tflite.py tries ai_edge_litert, then tflite_runtime).
if ! pkg install -y python-numpy python-pillow python-tflite-runtime; then
  echo "!! pkg install python-tflite-runtime failed. Try 'pkg update -y' then"
  echo "!! re-run; 'pkg search tflite' to check the name on your mirror."
  echo "!! Fallback (CPU-only, slower): a proot-distro Debian with"
  echo "!! 'pip install ai-edge-litert' — see phone/tier2-perception-tflite/README.md."
  exit 1
fi

echo "== 2/4: pip extras into the venv =="
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
pip install -q -r "$CORE_DIR/requirements-phone-perception.txt"

echo "== 3/4: converted models -> $DEST =="
mkdir -p "$DEST"
if [ -n "$SRC" ]; then
  if [ ! -d "$SRC" ]; then
    echo "!! $SRC is not a directory"; exit 1
  fi
  for f in "$SRC"/*.tflite; do
    [ -e "$f" ] || { echo "!! no .tflite files in $SRC"; exit 1; }
    if ! cmp -s "$f" "$DEST/$(basename "$f")"; then
      cp "$f" "$DEST/"
      echo "   copied $(basename "$f")"
    fi
  done
fi
MISSING=0
for m in "${MODELS[@]}"; do
  if [ -f "$DEST/${m}_${VARIANT}.tflite" ]; then
    echo "   ok   ${m}_${VARIANT}.tflite"
  else
    echo "   MISSING ${m}_${VARIANT}.tflite"
    MISSING=1
  fi
done
if [ "$MISSING" = 1 ]; then
  echo "!! Models missing. They're built on the desktop by"
  echo "!! phone/tier2-perception-tflite/convert.py into ~/.quintacle/perception/models/tflite/."
  echo "!! Either re-run the data migration (migrate-export.sh carries them) or copy"
  echo "!! that folder to the phone and run: bash $0 /path/to/that/folder"
  exit 1
fi

echo "== 4/4: smoke check =="
cd "$CORE_DIR"
QUINTACLE_DATA_DIR="$DATA_DIR" python - <<'PYEOF'
import os
os.environ.setdefault("QUINTACLE_PERCEPTION_BACKEND", "tflite")
os.environ.setdefault("QUINTACLE_TFLITE_VARIANT", "dynamic_range_quant")
from quintacle_core.perception import backend_tflite
mod = backend_tflite._interpreter_module()
print(f"  runtime: {mod.__name__}")
print(f"  available: {backend_tflite.available()}")
PYEOF

echo
echo "Done. Restart the backend (bash scripts/termux/update.sh, or kill uvicorn"
echo "and let the start-backend.sh loop bring it back) — photo drops then get"
echo "object tags + face matches on-device."
