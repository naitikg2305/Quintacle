# Running llama-server under Termux (Tier 3 vision lane)

Status: **written on desktop, 2026-10-15, not yet executed on the phone.**
Everything here is reality-checked against the Termux package repo and
llama.cpp's releases/docs as of that date, but no command below has run on
the S25U yet. The desktop equivalent (same server, same model, same
Quintacle client) is proven — see `README.md`.

## Install reality check (what's actually real)

- **`pkg install llama-cpp` is real.** Termux's official repo carries
  `llama-cpp` (termux-packages `packages/llama-cpp`, `TERMUX_PKG_VERSION=0.6.0`
  at check time, `TERMUX_PKG_AUTO_UPDATE=true`, aarch64 only — 32-bit arches
  are excluded). It is built with `-DGGML_BACKEND_DL=ON`, so GPU backends are
  separate loadable subpackages:
  - `llama-cpp-backend-opencl` → `libggml-opencl.so` (Adreno path; recommends
    `ocl-icd`, suggests `opencl-vendor-driver | clvk`)
  - `llama-cpp-backend-vulkan` → `libggml-vulkan.so`
  Caveats: the packaged version lags upstream (0.6.0 vs 0.7.0-dev that the
  desktop smoke used), and whether the package ships `llama-server` (vs only
  `llama-cli`) must be verified on-device — `build-or-install.sh` checks and
  falls back to the source lane.
- **Upstream prebuilt Android binaries exist too**: every llama.cpp GitHub
  release ships `llama-<build>-bin-android-arm64.tar.gz` and
  `llama-<build>-bin-android-arm64-snapdragon.tar.gz` (the Snapdragon variant
  carries the Adreno/Hexagon-targeted backends). These are built for
  adb/NDK-style environments; under Termux prefer the pkg or source lanes,
  but they are the escape hatch if the Termux package is broken or stale.
- **Source build in Termux**: `pkg install git cmake clang ocl-icd
  opencl-headers opencl-vendor-driver`, then cmake with `-DGGML_OPENCL=ON`
  per llama.cpp `docs/backend/OPENCL.md` (which targets exactly this class
  of device — Adreno 7xx/8xx). The Adreno driver is exposed to Termux via
  the `opencl-vendor-driver` package (symlinks `/vendor/lib64/libOpenCL.so`
  into the ICD path); `clvk` (OpenCL over Vulkan) is the fallback if the
  vendor ICD misbehaves. The experimental Hexagon (NPU) backend is NOT
  expected to work from Termux — `docs/on-device-s25u.md` already wrote off
  NPU-from-Termux; that path belongs to the eventual APK-native module.

## Steps (in order, on the phone)

```sh
# 0. Termux basics
pkg update && pkg install -y curl

# 1. Server binary (pkg lane first; falls back with instructions)
./build-or-install.sh          # or: ./build-or-install.sh source

# 2. Model + mmproj (~3.1GB, checksummed, resumable)
./fetch-model.sh ~/models/qwen2.5-vl-3b

# 3. CPU first — prove correctness before touching the GPU backend
llama-server \
  -m ~/models/qwen2.5-vl-3b/Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf \
  --mmproj ~/models/qwen2.5-vl-3b/mmproj-Qwen2.5-VL-3B-Instruct-f16.gguf \
  --host 127.0.0.1 --port 8080 -c 8192

# 4. Smoke it raw (no Quintacle yet): health, then one image question
curl -s http://127.0.0.1:8080/health
# then an OpenAI-style /v1/chat/completions with an image_url data URL —
# or just point the Quintacle core at it (step 5) and let the real client
# be the test.

# 5. The actual Quintacle smoke — identical to the desktop proof:
#    run the core (Termux backend per docs/termux-backend-setup.md) with
QUINTACLE_VISION=local \
QUINTACLE_VISION_BACKEND=llamacpp \
QUINTACLE_LLAMACPP_URL=http://127.0.0.1:8080 \
  uvicorn quintacle_core.api:app --port 8000
#    and POST /kb/asset/describe for a stored photo.

# 6. Only after CPU works: retry with the OpenCL backend installed
#    (llama-cpp-backend-opencl + opencl-vendor-driver) and compare the
#    print_timing lines. If OpenCL crashes or is slower on the vision
#    encoder, CPU is the lane — record it either way.
```

## What to record (first-benchmark protocol)

llama-server prints, per request:

```
prompt eval time = ... ms / N tokens (... tokens per second)   <- PREFILL
       eval time = ... ms / N tokens (... tokens per second)   <- DECODE
```

The prefill/decode split is the plan doc's named unknown
(`docs/local-vision-phone-plan.md`): all published S25U-class numbers are
text *decode*; image-token *prefill* through the mobile backends is
unmeasured, and on desktop CPU it was ~95% of total latency. Record, for
the same photo, CPU vs OpenCL:

1. prefill tok/s and decode tok/s (the two print_timing lines);
2. wall time of `/kb/asset/describe` (what the user feels);
3. image size sensitivity: the desktop smoke's 12MP photo became ~4000
   image tokens; repeat with the same photo downscaled to ~1MP — if
   prefill dominates on the phone as it does on desktop CPU, downscaling
   before upload is the single biggest lever;
4. battery/thermals over a 20-photo batch (the "overnight on charger"
   soak from the plan doc);
5. peak RSS of llama-server (RAM budget below).

Write results back into `docs/on-device-s25u.md`.
