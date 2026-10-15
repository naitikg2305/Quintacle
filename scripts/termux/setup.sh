#!/data/data/com.termux/files/usr/bin/bash
# Quintacle — Termux backend bootstrap.
#
# Run this INSIDE Termux on the phone (not on a desktop). It installs Python
# and the system packages the backend's dependencies need to build/import on
# Termux's Bionic-libc userland, then creates a venv and installs
# core/requirements.txt into it.
#
# Full context: docs/termux-backend-setup.md and docs/android-apk-migration.md
#
# Usage (from anywhere, after this repo is on the phone — see
# docs/termux-backend-setup.md for how to get the repo itself onto the
# phone, e.g. `pkg install git && git clone ...` or copying a tarball):
#   bash scripts/termux/setup.sh
#
# Safe to re-run; every step is idempotent (pkg install / pip install skip
# what's already satisfied).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
CORE_DIR="$REPO_ROOT/core"
VENV_DIR="$CORE_DIR/.venv"

if [ -z "${PREFIX:-}" ] || [ ! -d "${PREFIX:-/nonexistent}" ]; then
  echo "!! \$PREFIX is not set to a Termux install — this script is Termux-only"
  echo "!! (it calls 'pkg', which only exists inside Termux). Aborting."
  exit 1
fi

echo "== 1/5: updating Termux package lists =="
pkg update -y
pkg upgrade -y

echo "== 2/5: installing system packages =="
# python            - interpreter + pip
# binutils          - provides aarch64-linux-android-ar etc., needed by the
#                     rust/cargo build below
# rust              - pydantic-core (pulled in by pydantic v2, a transitive
#                     dependency of fastapi) ships no prebuilt wheel for
#                     Termux's Bionic-libc aarch64 target, so pip builds it
#                     from source via cargo. This is a real ~10 minute
#                     build with a sizeable download the first time — expect
#                     it, don't interrupt it.
# clang / make /
# pkg-config        - general C build toolchain for any other sdist fallback
#                     (e.g. PyYAML's optional C extension via
#                     python-frontmatter)
# libjpeg-turbo,
# libxml2, libxslt,
# openssl           - headers some of the packages below link against
# python-pillow     - prebuilt Pillow for Termux. Do NOT let pip build this
#                     from source (see note below) — installed via pkg so a
#                     working libjpeg/zlib-linked build is guaranteed.
# python-numpy      - same story: opencv's own prebuilt package depends on
#                     this, and a pip source build of numpy is painful here.
# opencv-python     - Termux's own prebuilt package (Termux-main repo) that
#                     provides the `cv2` module. THIS IS THE RISKY ONE — see
#                     the big warning below.
# python-lxml       - prebuilt lxml (python-docx's dependency); a pip source
#                     build of lxml needs libxml2/libxslt dev headers that
#                     are fiddly to get right on Termux.
pkg install -y \
  python \
  binutils rust clang make pkg-config \
  libjpeg-turbo libxml2 libxslt openssl \
  python-pillow python-numpy python-lxml \
  git curl

echo "== 3/5: installing opencv-python (cv2) — may not be available =="
# core/quintacle_core/nodes/kb/drop.py does `import cv2` at MODULE LOAD TIME
# (not inside a function), and that module is imported by api.py. That means
# if cv2 is missing, the WHOLE FastAPI app fails to start, not just the
# video-frame-extraction feature that's the only thing that actually uses
# cv2. This was flagged to the app's maintainer rather than silently patched
# (see docs/termux-backend-setup.md for the recommended lazy-import fix, not
# applied here per scope).
if ! pkg install -y opencv-python; then
  echo
  echo "!! 'pkg install opencv-python' failed or that package isn't in your"
  echo "!! Termux repos right now. The backend will NOT start without cv2"
  echo "!! importable. Try, in order:"
  echo "!!   1. pkg install x11-repo && pkg install opencv-python"
  echo "!!   2. pkg search opencv   (check the exact package name on your"
  echo "!!      Termux version — it has moved/been renamed before)"
  echo "!!   3. As a last resort, a from-source pip build via"
  echo "!!      'pkg install cmake ninja && pip install numpy opencv-python-headless'"
  echo "!!      is reported to sometimes work but can take a very long time"
  echo "!!      and fails outright on some Termux/Android versions."
  echo "!! See docs/termux-backend-setup.md for the full writeup."
  echo
fi

echo "== 4/5: creating venv (with access to the pkg-installed C-extension modules) =="
# --system-site-packages is required so the venv can see the Pillow/numpy/
# opencv/lxml modules installed via `pkg` above (those are not pip packages
# and pip has no idea they exist otherwise — without this flag, the next
# step would try to pip-install Pillow/opencv-python-headless itself and
# very likely fail to build them from source).
if [ ! -d "$VENV_DIR" ]; then
  python -m venv --system-site-packages "$VENV_DIR"
fi
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
pip install --upgrade pip wheel setuptools

echo "== 5/5: installing core/requirements.txt (minus pkg-provided packages) =="
# Pillow and opencv-python-headless are deliberately dropped from the list
# pip sees: they're already provided by the pkg-installed python-pillow /
# opencv-python above, and letting pip "help" by trying to install its own
# copy is exactly the scenario --system-site-packages is meant to avoid.
FILTERED_REQS="$(mktemp)"
grep -viE '^(Pillow|opencv-python-headless)\s*$' "$CORE_DIR/requirements.txt" > "$FILTERED_REQS"
pip install -r "$FILTERED_REQS"
rm -f "$FILTERED_REQS"

echo
echo "== Sanity-checking imports =="
python - <<'PYEOF'
import importlib
mods = ["fastapi", "uvicorn", "pydantic", "anthropic", "openai", "PIL", "numpy", "lxml", "docx", "openpyxl", "cv2"]
failed = []
for m in mods:
    try:
        importlib.import_module(m)
        print(f"  ok   {m}")
    except Exception as exc:
        failed.append(m)
        print(f"  FAIL {m}: {exc}")
if failed:
    print()
    print(f"!! These failed to import: {', '.join(failed)}")
    print("!! If 'cv2' is the only failure, the API will not start at all")
    print("!! (see the warning above) until it's resolved.")
PYEOF

echo
echo "Done. Next steps:"
echo "  1. cp $CORE_DIR/.env.example $CORE_DIR/.env   (then edit in your API keys)"
echo "  2. Migrate your real data — see scripts/termux/migrate-import.sh and"
echo "     docs/termux-backend-setup.md"
echo "  3. bash scripts/termux/start-backend.sh --once   (test it runs)"
echo "  4. Set up Termux:Boot persistence — see docs/termux-backend-setup.md"
echo "  5. Optional, Tier 1 local LLM (free on-device chat via the 'local:' models):"
echo "     bash phone/tier1-local-llm/install-ollama-termux.sh"
echo "     — installs Ollama + pulls qwen2.5:1.5b; see phone/tier1-local-llm/README.md"
