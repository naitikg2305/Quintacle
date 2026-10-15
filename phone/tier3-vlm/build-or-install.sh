#!/usr/bin/env bash
# Get a llama-server onto the phone (Termux). Three lanes, tried in order of
# least effort — reality-checked 2026-10-15 (see run-llamacpp-termux.md):
#
#   pkg      Termux's OFFICIAL llama-cpp package (it exists: termux-packages/
#            packages/llama-cpp, v0.6.0 at check time, auto-updated, aarch64
#            only) + its GPU backend subpackages. Easiest; lags upstream.
#   release  Prebuilt upstream binaries: llama.cpp GitHub releases ship
#            llama-<build>-bin-android-arm64.tar.gz and a -snapdragon variant.
#            Newest code, but glibc-style binaries made for adb/NDK
#            environments — under Termux prefer the pkg or source lanes.
#   source   Build from source inside Termux with the OpenCL (Adreno) backend
#            per llama.cpp's docs/backend/OPENCL.md. Slowest, most control.
#
# Usage: ./build-or-install.sh [pkg|source]   (default: pkg)
set -euo pipefail

LANE="${1:-pkg}"

if [ -z "${PREFIX:-}" ] || ! command -v pkg >/dev/null 2>&1; then
  echo "error: this script expects to run inside Termux on the phone." >&2
  echo "On desktop, use a llama.cpp release binary or your distro package." >&2
  exit 1
fi

case "$LANE" in
  pkg)
    echo "== Installing Termux's llama-cpp package + OpenCL backend =="
    pkg install -y llama-cpp llama-cpp-backend-opencl || {
      echo "pkg install failed — repo out of sync? Try: pkg update, then re-run." >&2
      exit 1
    }
    # The OpenCL backend needs an ICD loader + the vendor driver exposed to
    # Termux (Adreno's libOpenCL.so lives in /vendor/lib64).
    pkg install -y ocl-icd opencl-vendor-driver || true
    ;;
  source)
    echo "== Building llama.cpp from source in Termux (OpenCL for Adreno) =="
    pkg install -y git cmake clang ocl-icd opencl-headers opencl-vendor-driver
    src="$HOME/src/llama.cpp"
    if [ -d "$src/.git" ]; then git -C "$src" pull --ff-only; else
      mkdir -p "$HOME/src" && git clone --depth 1 https://github.com/ggml-org/llama.cpp "$src"
    fi
    cmake -S "$src" -B "$src/build" \
      -DCMAKE_BUILD_TYPE=Release \
      -DGGML_OPENCL=ON \
      -DLLAMA_CURL=OFF \
      -DLLAMA_BUILD_TESTS=OFF
    cmake --build "$src/build" --target llama-server -j "$(nproc)"
    mkdir -p "$PREFIX/bin"
    cp "$src/build/bin/llama-server" "$PREFIX/bin/"
    ;;
  *)
    echo "usage: $0 [pkg|source]" >&2
    exit 2
    ;;
esac

echo
if command -v llama-server >/dev/null 2>&1; then
  echo "llama-server installed: $(command -v llama-server)"
  llama-server --version || true
else
  echo "warning: llama-server not on PATH after install." >&2
  echo "If the pkg lane shipped only llama-cli, fall back to: $0 source" >&2
  exit 1
fi
echo "Next: ./fetch-model.sh, then see run-llamacpp-termux.md"
