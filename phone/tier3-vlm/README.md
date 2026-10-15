# Tier 3 — experimental on-device VLM lane (photo descriptions)

The third tier of Quintacle's phone stack: run the photo-description VLM
on the phone itself, behind the same `describe_images()` contract the
cloud and desktop paths already use. Ollama does not exist on Android, so
this lane standardizes on **llama.cpp's `llama-server`** — the one
runtime that serves the same GGUF on desktop Linux and under Termux.

## Honest status (2026-10-15)

| Piece | Status |
|---|---|
| Client (`core/quintacle_core/local_vlm/llamacpp.py`) | **Desktop-proven, end-to-end.** Real `llama-server` (prebuilt b11669) + Qwen2.5-VL-3B-Instruct Q4_K_M + f16 mmproj, driven through the actual `/kb/asset/describe` endpoint with a real 12MP phone photo. Correct descriptions on both CPU and CUDA runs. |
| Backend switch (`QUINTACLE_VISION_BACKEND=ollama\|llamacpp`) | Done; default `ollama`; lives inside `local_vlm.describe_images_local()` so the `QUINTACLE_VISION` dispatch in `drop.py` is untouched. |
| Termux install path (`build-or-install.sh`) | Reality-checked against the Termux repo (official `llama-cpp` package + OpenCL subpackage exist) but **never executed on a phone**. |
| On-device inference | **Wholly unproven.** No command in this folder has run on the S25U. |

## Desktop proof numbers (same model/server the phone will run)

Machine: Linux laptop, RTX 5070 Ti (12GB), llama.cpp b11669 prebuilt
binaries; photo: real 12MP camera JPEG (~3.7MB → ~4,000 image tokens).

| Run | Prefill (image+prompt) | Decode | Wall time via `/kb/asset/describe` |
|---|---|---|---|
| CPU only | 210.6s / 4055 tok (**19.3 tok/s**) | 10.6 tok/s | **3m41s** |
| CUDA, full offload | 7.1s / 4064 tok (**574 tok/s**) | 72.6 tok/s | **7.6s** (0.9s repeat — image KV cached) |

Two lessons the phone inherits:

1. **Prefill dominates** — on CPU it was ~95% of latency. The phone
   question is not "can it decode" (published S25U numbers say yes) but
   "how fast is image prefill through OpenCL/CPU" — the plan doc's named
   unknown. Downscaling photos before describe is the biggest lever.
2. **Q4 quality wobbles** — the same photo was described correctly twice
   ("black ASUS laptop on a wooden surface") and once as a "desktop
   computer tower". Fine for KB captions, but run the acceptance pass from
   `docs/test-plan-and-wishlist.md` against stored cloud captions before
   trusting it for batch re-tagging.

## RAM budget on the 12GB phone

| Component | ~Size |
|---|---|
| Qwen2.5-VL-3B Q4_K_M weights | 1.9 GB |
| mmproj f16 (vision encoder) | 1.3 GB (Q8_0 variant exists at 0.8 GB) |
| KV cache @ 8k ctx + runtime | ~0.5 GB |
| Vision-encoder compute buffer | up to ~1.4 GB for a 12MP image (measured on desktop; shrinks hard with downscaled input) |
| **llama-server peak** | **~5 GB worst case, ~4 GB with sane image sizes** |

Against 12 GB total: Android + system ~3–4 GB, Termux + Quintacle core
~1 GB, Tier 2 perception models (YOLO + face embedder) ~0.5 GB. That sums
to ~9–10.5 GB — *plausible but tight*, exactly as
`docs/local-vision-phone-plan.md` predicted. Mitigations, in order:
downscale images (cuts the encoder buffer), Q8_0 mmproj (−0.5 GB),
one-model-at-a-time loading, and as the floor the ≤2B degraded tier.

## The graceful story (why this lane is allowed to fail)

This tier is experimental **by contract, not just by label**:

- `QUINTACLE_VISION=auto` means: try local, and if `llama-server` is down,
  OOM-killed, thermally dead, or just absent, `describe_images_local()`
  returns `None` and the call **falls back to cloud descriptions** with a
  log line. A broken Tier 3 costs money, never functionality.
- `QUINTACLE_VISION=local` is the strict mode: it raises rather than
  silently billing the cloud — for when the whole point is that the photo
  must not leave the device.
- **Identity never leaves either way**: faces, person matching, and object
  tags are Tier 2 (`perception/`, on-device), independent of this lane.
  Tier 3 failing means photo *captions* come from the cloud; it never
  changes where *face embeddings* live.

## Files

- `fetch-model.sh` — checksummed, resumable download of the GGUF + mmproj
  (works on desktop and in Termux; refuses without 4GB free disk).
- `build-or-install.sh` — Termux install: official `llama-cpp` package
  first (verified to exist), source build with OpenCL as fallback.
- `run-llamacpp-termux.md` — the on-phone runbook + the first-benchmark
  protocol (prefill/decode split, image-size sensitivity, thermals).

## Pointing Quintacle at it

```sh
QUINTACLE_VISION=auto                      # or `local` for strict privacy
QUINTACLE_VISION_BACKEND=llamacpp
QUINTACLE_LLAMACPP_URL=http://127.0.0.1:8080   # llama-server default
```

No GGUFs or binaries live in git — scripts fetch them.
