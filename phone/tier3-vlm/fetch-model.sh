#!/usr/bin/env bash
# Fetch the Tier-3 vision model: Qwen2.5-VL-3B-Instruct GGUF (Q4_K_M) plus its
# mmproj (the vision encoder — llama-server cannot see images without it).
#
# Runs anywhere with bash+curl: desktop Linux or Termux on the phone.
# Idempotent: resumes partial downloads (-C -) and skips files whose sha256
# already verifies. ~3.1GB total; refuses to start without 4GB free.
#
# Usage: ./fetch-model.sh [dest-dir]     (default: ./models)
set -euo pipefail

DEST="${1:-./models}"
BASE="https://huggingface.co/ggml-org/Qwen2.5-VL-3B-Instruct-GGUF/resolve/main"

# name|sha256 — hashes verified against the copies that passed the desktop
# smoke on 2026-10-15 (see README.md). If upstream re-uploads, re-pin.
FILES=(
  "Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf|d02fe9b69ad8cadbbd228e387667af66612c44bed29ffc8eb1e7caf9ac486c12"
  "mmproj-Qwen2.5-VL-3B-Instruct-f16.gguf|b9160fe9d814d1fadf68395677468534778b39ac33c2e7561b7b218626e60d5e"
)

NEED_MB=4096
mkdir -p "$DEST"
avail_mb=$(df -Pm "$DEST" | awk 'NR==2 {print $4}')
if [ "$avail_mb" -lt "$NEED_MB" ]; then
  echo "error: only ${avail_mb}MB free at $DEST — need ~${NEED_MB}MB for model + mmproj" >&2
  exit 1
fi

verify() { # verify <path> <sha256>
  echo "$2  $1" | sha256sum -c --status
}

for entry in "${FILES[@]}"; do
  name="${entry%%|*}"
  sha="${entry##*|}"
  path="$DEST/$name"
  if [ -f "$path" ] && verify "$path" "$sha"; then
    echo "ok (cached): $name"
    continue
  fi
  echo "fetching: $name"
  curl -L -C - --fail --progress-bar -o "$path" "$BASE/$name"
  if ! verify "$path" "$sha"; then
    echo "error: sha256 mismatch for $name — deleting the corrupt file; re-run to retry" >&2
    rm -f "$path"
    exit 1
  fi
  echo "ok (verified): $name"
done

echo
echo "Model files ready in $DEST:"
ls -lh "$DEST"
echo
echo "Serve with:"
echo "  llama-server -m $DEST/Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf \\"
echo "    --mmproj $DEST/mmproj-Qwen2.5-VL-3B-Instruct-f16.gguf \\"
echo "    --host 127.0.0.1 --port 8080 -c 8192"
