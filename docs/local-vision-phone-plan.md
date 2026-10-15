# Local vision on the phone — plan (not built)

Status: **plan, 2026-10-15. Nothing phone-side is built.** Grounded in
three things: what NaviGatr actually ran on Pi-class hardware
(`docs/navigatr-vlm-notes.md`), the S25U NPU research
(`docs/on-device-s25u.md`), and the desktop local-vision code that now
exists (`core/quintacle_core/local_vlm/` + the `QUINTACLE_VISION` dispatch
in `core/quintacle_core/nodes/kb/drop.py`). Everything S25U-specific below
inherits the caveats of `on-device-s25u.md` — most numbers are model-card
numbers, not measurements from this phone.

## Why the floor is believable

NaviGatr ran a per-frame, real-time pipeline — int8 SSD MobileNet v2
detection + int8 FER emotion — on a Raspberry Pi 5 with a **~4 TOPS**
Coral USB TPU, and only had to offload monocular depth. The S25U's Hexagon
NPU is an order of magnitude more compute (~60 TOPS-class, W4A16
transformer decode, 12GB host RAM) and already demonstrably decodes 3B
LLMs at ~26 tok/s (AI Hub cards, see `on-device-s25u.md`). So a Pi 5 +
Coral is a conservative *floor* for a flagship phone NPU: everything
NaviGatr proved on the Pi — perception models per frame, conditional
cascades, bytes-over-HTTP to whatever doesn't fit — fits on the phone with
headroom, and the thing NaviGatr had to offload (a heavy model) is in 2026
a 1–4B VLM that the phone can host itself.

## The two-lane split (same shape as desktop)

Quintacle's vision work is splitting into two lanes, and they want
*different runtimes* on the phone:

1. **Perception lane** — `core/quintacle_core/perception/` with
   `perceive_photo()` (YOLO-class detection + face embedding; being built
   by a parallel effort — this doc only references its contract, the
   structured per-photo output of detections/faces). These are NaviGatr's
   kind of models: small, quantized, fixed-shape CNNs/ViTs.
2. **Description lane** — `describe_images()` / `describe_images_local()`:
   open-ended "what is this photo" and "answer this question about it".
   This needs an actual VLM.

### Recommended phone stack, per model

| Job | Model class | Runtime on S25U | Why |
|---|---|---|---|
| Object detection (perception lane) | YOLO11n / YOLO-class, int8 | **TFLite (LiteRT) + NNAPI/QNN delegate** | Direct descendant of NaviGatr's EdgeTPU TFLite path; NaviGatr already produced `yolo11n_int8.tflite` (`pi_develop:src/obj_detect/`). Fixed shapes, int8, delegate-friendly — exactly what NNAPI/Hexagon eat. |
| Face detect + embed (perception lane) | BlazeFace/SCRFD + MobileFaceNet-class embedder, int8 | **TFLite + NNAPI/QNN delegate** (MediaPipe Tasks where it fits) | Same reasoning; embeddings POST back to the core for storage, mirroring the S25U doc's EmbeddingGemma pattern. |
| Photo description / photo Q&A | **1–4B VLM** | **llama.cpp-android first** (GGUF, Adreno OpenCL today, experimental Hexagon backend), **LiteRT-LM as the alternate** (Gemma vision models, GPU today, NPU when GA) | llama.cpp = any GGUF, including the exact model family the desktop runs; LiteRT-LM = fewer moving parts + the embeddings stack already wants it. |
| Text embeddings (already planned) | EmbeddingGemma | LiteRT-LM | Unchanged from `on-device-s25u.md`. |

### VLM candidates (1–4B class), in order

1. **Qwen2.5-VL 3B / Qwen3-VL-class small** — what the desktop now runs
   (`local_vlm/ollama.py`, default `qwen2.5vl:3b`): in the desktop smoke it
   described a scene correctly *and read embedded text verbatim*, which
   matters for Quintacle's receipts/labels/documents. Apache-2.0, GGUF
   available, ~2–3GB at Q4. First choice if llama.cpp's Android backends
   handle its vision encoder acceptably.
2. **Gemma 3 4B (vision) / Gemma-class via LiteRT-LM** — the path with
   vendor-supported Android tooling and the lowest integration risk, at
   the cost of model choice.
3. **SmolVLM2 / Moondream-class (≤2B)** — only if RAM/thermals force it.
   The desktop smoke showed moondream's output is markedly worse
   (truncated, garbled on the same image); treat this tier as a
   degraded mode, not the plan.

Expected feel: a one-photo description is a few hundred tokens of prefill
(image tokens) + ~100 tokens of decode. At the S25U's measured 2B–3B
decode rates (26–52 tok/s), that is **a handful of seconds per photo,
single digits of Wh** — fine for on-demand describe, and batch photo
tagging goes to the "on charger, overnight" bucket exactly as
`on-device-s25u.md` already prescribes for 8B-class work.

## What ports, what gets rewritten

Ports as-is (the point of the dispatch design):

- **The provider switch** — `describe_images()` consults
  `QUINTACLE_VISION` per call; every call site (drop-time, `/kb/asset/
  describe`, MCP `describe_photo`) inherits it. On the phone (Termux
  backend per `docs/android-apk-migration.md` / `docs/termux-backend-setup.md`),
  the same Python runs unchanged.
- **`local_vlm/ollama.py` nearly as-is for the intermediate step**: it is
  ~80 lines of "POST JSON+base64 to a localhost HTTP server". llama.cpp's
  `llama-server` runs under Termux (CPU, usually OpenCL GPU) and speaks an
  OpenAI-compatible API; adding a second ~80-line client module (or an
  env-selected URL/format) is the whole change. This is phase B of the
  S25U doc, applied to vision.
- **The prompt** — `vision_prompt()` in `core/quintacle_core/nodes/
  vision.py` is backend-agnostic by construction.

Rewrites (cannot port):

- **The VLM runtime itself for NPU**: Ollama does not exist on Android;
  the NPU path means llama.cpp-android with the Hexagon backend or a
  GenieX/LiteRT-LM Kotlin module inside the APK (option A in
  `on-device-s25u.md`), exposing `describe(image, prompt)` to the web
  layer next to the planned `narrate/extract/embed` calls.
- **The perception lane**: desktop `perceive_photo()` will run
  PyTorch/ONNX-class Python; the phone version is TFLite models behind a
  thin Kotlin/MediaPipe layer, re-exporting the *same weights* (YOLO →
  int8 TFLite, as NaviGatr already did once). The contract (structured
  detections/faces JSON) is what ports, not the code.
- **Frame/photo ingestion**: NaviGatr's `libcamera-still` subprocess trick
  has no Android equivalent; photos arrive through the app/share-sheet
  instead — already Quintacle's drop model, so nothing new, just *not*
  reusable code.

## Honest unknowns until a device is in hand

- **Vision prefill speed on the NPU.** All measured S25U-class numbers in
  `on-device-s25u.md` are *text* decode; image-token prefill through
  llama.cpp's Hexagon/OpenCL backends is unmeasured here, and vision
  encoders (ViT front-ends) are often the part that falls off the
  accelerated path and lands on CPU. Could swing total latency 5–10x.
- **Whether llama.cpp's Android backends run the chosen VLM's mmproj/
  vision encoder at all** (Hexagon backend is experimental; quant support
  Q4_0/Q8_0-centric). If not: LiteRT-LM + Gemma vision becomes the
  primary, not the alternate.
- **Termux vs APK reality**: NPU from Termux is already written off
  (`on-device-s25u.md`); whether OpenCL-GPU llama-server under Termux is
  stable enough for the intermediate phase is untested on this exact
  phone/ROM.
- **RAM pressure on the 12GB model**: 3B VLM (~3GB) + EmbeddingGemma +
  detector + the app + Android itself, concurrently, is plausible but
  unproven; may force the ≤2B degraded tier or strict one-model-at-a-time
  loading.
- **Thermals for batch tagging**: "overnight on charger" is the plan, but
  sustained vision prefill is heavier per token than text decode; needs a
  real soak test.
- **Quality at Q4 on *user* photos**: the desktop smoke was one synthetic
  image on an unquantized-ish GPU build. Cluttered real-world photos, at
  mobile quantization, judged against the cloud captions already stored in
  the KB, is the acceptance test (reuse the plan in
  `docs/test-plan-and-wishlist.md`).

## Sequence (when a device is in hand)

1. Termux: build/install `llama-server`, load the chosen VLM GGUF (CPU
   first), point `QUINTACLE_OLLAMA_URL`-equivalent at it, run the same
   smoke as the desktop (`QUINTACLE_VISION=local` + `/kb/asset/describe`).
   Zero Kotlin, answers the quality question and most of the speed one.
2. Benchmark the perception-lane TFLite models through NNAPI with a
   stock benchmarker before writing any integration code.
3. Only then decide GenieX vs LiteRT-LM for the APK's native module, with
   the measured numbers written back into `on-device-s25u.md`.
