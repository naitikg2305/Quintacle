# NaviGatr archaeology — what the Pi branches actually ran

Status: research notes, 2026-10-15. Source: read-only clone of
`github.com/naitikg2305/Navigatr` at `/tmp/navigatr` (not committed here).
Branches examined: `pi_main`, `pi_develop`, `pi-eliav` (the Pi line), plus
`objDet`/`objDet2` (the detection research line). Citations are
`branch:path` in that clone.

## The honest headline

**NaviGatr never ran a language VLM on the Pi.** A grep across all eight
branches for moondream/llava/llama/smolvlm/minicpm/ollama/openai/anthropic
finds nothing but vendored emoji tables and COCO label output. What the Pi
branches actually ran is a *multi-model perception pipeline* — small
quantized single-task vision models on a Coral EdgeTPU, with the one model
too heavy for the Pi offloaded over HTTPS to a GPU server — and the
"descriptions" were template sentences over detector output, spoken via
TTS. That pattern (small local models first, network for what doesn't
fit) is the real prior art Quintacle inherits; the describer model itself
is new.

## The pipeline, per frame (Raspberry Pi 5 + Coral USB TPU)

Entry points: `pi_main:src/run_Pi_Thread.py` (threads + queues) and its
successor `pi-eliav:src/run_futures.py` (one `ProcessPoolExecutor` per
model, `max_workers=1`, spawn start method).

1. **Frame in** — shell out to `libcamera-still -n -t 100 -o - --encoding
   jpg` and take the JPEG bytes off stdout (`capture_frame()` in both entry
   points). No V4L2/picamera2 bindings; literally one subprocess per frame.
2. **Object detection, local, EdgeTPU** — `ssd_mobilenet_v2_coco_quant_
   postprocess_edgetpu.tflite` (COCO, int8, EdgeTPU-compiled) through
   `pycoral.utils.edgetpu.make_interpreter` + `pycoral.adapters.detect`,
   score threshold 0.4, boxes rescaled to frame size
   (`pi-eliav:src/objectDetection/object_executor.py`).
3. **Depth, OFFLOADED** — monocular depth (Apple **Depth Pro**: the
   `depth-pro/checkpoints/depth_pro.pt` checkpoint sits in
   `pi_develop:src/distance/`; research trail in
   `pi_develop:docs/monoptic-depth-estimation.md` — MiDaS/ZoeDepth/
   MonoDepth2 considered, metric depth required) was too heavy for the Pi,
   so the frame is POSTed as JPEG to a bearer-token HTTPS API on an AWS
   EC2 box, which returns the depth map as an `np.load`-able byte stream
   (`pi-eliav:src/distance/depth_executor.py`, `api-config.json`,
   self-signed `cert.pem`, startup `liveness_check()` in
   `api_liveness.py`).
4. **Emotion, local, EdgeTPU, conditional** — only when a detected
   `person` is closer than 1m, the person crop is re-encoded to JPEG bytes
   and run through `fer_emotion_model_int8_edgetpu.tflite` (7-class FER,
   int8) (`pi-eliav:src/run_futures.py`,
   `pi-eliav:src/EmotionDetec/emotion_executor.py`).
5. **"Description" out** — per object: label + clock-direction (frame
   width cut into octiles mapped to "10 o'clock"…"2 o'clock") + min depth
   inside the box, formatted as a template sentence and spoken — espeak-ng
   on `pi-eliav` (fully offline), Microsoft `edge-tts` (cloud voice) on
   `pi_main:src/text_to_speech.py`. The natural-language layer is string
   formatting, not a model.

## Pi-specific tricks worth keeping

- **Quantize + delegate**: everything local is int8 TFLite compiled for
  the EdgeTPU; `pi_main:requirements.txt` is just numpy/opencv/Pillow +
  vendored aarch64 wheels for `tflite-runtime 2.5.0.post1` and
  `pycoral 2.0.0` (pinned to Python 3.9 — the README calls this out as a
  hard compatibility constraint).
- **Bytes between processes**: frames and crops cross process boundaries
  as encoded JPEG bytes, not ndarrays — the pi-eliav commits
  ("switched to byte streams", "frame copy for safe pickling",
  "picklable emotion") record them learning that lesson for
  `ProcessPoolExecutor`.
- **One process per model**: each model gets its own single-worker
  process pool with the interpreter built once in the pool initializer —
  model load paid once, inference calls stay hot.
- **Conditional cascade**: the expensive extra model (emotion) only runs
  when a cheap gate (person within 1m) fires.
- **Fail loud on the network dependency**: the depth API gets a liveness
  check at startup with explicit, user-readable failures for cert/key/
  connectivity, instead of dying mid-loop.
- **Latency handling** was concurrency, not cleverness: detection and
  depth run in parallel per frame; `pi_main` throttled with a 0.5s sleep
  between frames. No frame skipping, no async queues beyond that.

The `objDet`/`objDet2` line is the research track that fed this: NanoDet
first (`pi_develop:docs/SetupGuideforNanoDetTesting.md`), then YOLO11n in
.pt/.onnx/int8-tflite form (`pi_develop:src/obj_detect/`, including a
`coral_test_ultralytics.py`), with the anchor-free model survey in
`pi_develop:docs/obj_detect_research.md`. The shipped Pi build settled on
the proven Coral SSD MobileNet instead.

## What this means for Quintacle

- The lineage is **split by weight**: perception-class models (detector,
  small classifiers) run on-device; anything heavier goes over localhost/
  network HTTP with a graceful failure path. Quintacle's
  `QUINTACLE_VISION=auto` (try local VLM, fall back to cloud with a log
  line — `core/quintacle_core/nodes/kb/drop.py::describe_images`) is the
  same shape with the roles updated: in 2026 a 3B VLM *is* small enough to
  be the local half.
- NaviGatr talked to its heavy model over plain HTTP with multipart JPEG —
  Quintacle's local backend does the same over Ollama's localhost API
  (`core/quintacle_core/local_vlm/ollama.py`), zero new dependencies.
- A Pi 5 + 4-TOPS Coral ran three models per frame in real time. That is
  the floor the phone plan builds on — see
  `docs/local-vision-phone-plan.md`.

## Desktop smoke (this machine, 2026-10-15)

`qwen2.5vl:3b` via Ollama (RTX 5070 Ti laptop GPU, 100% GPU resident,
~0.8s warm per description) through the real `/kb/asset/describe` endpoint
with `QUINTACLE_VISION=local` correctly described a synthetic house/sun
scene *and read the embedded text verbatim* ("QUINTACLE TEST 42").
`moondream` (1.7GB) on the same image produced truncated, garbled output —
hence qwen2.5vl:3b as the default `QUINTACLE_VISION_MODEL`.
