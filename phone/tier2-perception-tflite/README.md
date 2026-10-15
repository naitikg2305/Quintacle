# Tier 2 — Perception models on TFLite (phone NPU lane, code-ready)

Status: **built and parity-proven on desktop, 2026-10-15. No device has run
this yet** — everything NNAPI/QNN-specific below is wired but unproven.

This tier converts the three ONNX models the desktop perception lane runs
(`core/quintacle_core/perception/`: YOLOX-nano object tags, SCRFD-500M face
detect, ArcFace w600k_mbf face embed) to TFLite, adds a LiteRT runtime
backend behind `QUINTACLE_PERCEPTION_BACKEND=tflite`, and proves — on real
photos, on this desktop — that both backends compute the same tags, boxes and
face embeddings. It is the direct descendant of NaviGatr's int8-TFLite-on-
accelerator pipeline (Pi 5 + Coral; see `docs/navigatr-vlm-notes.md` and
`docs/local-vision-phone-plan.md`): same weights, same int8-TFLite shape the
S25U's NNAPI/Hexagon path eats.

## Layout

| piece | where | runs on |
|---|---|---|
| conversion pipeline | `convert.py` (+ `convert-requirements.txt`) | its own Python 3.12 venv, desktop only |
| runtime backend | `core/quintacle_core/perception/backend_tflite.py` | the normal core venv (Python 3.14) / the phone |
| parity harness | `parity.py` | core venv, desktop |
| converted models | `~/.quintacle/perception/models/tflite/` | **never committed** — build artifacts |

## Conversion walkthrough

The conversion toolchain (onnx2tf 2.6.9 + tensorflow 2.21) does not support
Python 3.14, so it lives in its own venv and never touches the runtime:

```bash
cd phone/tier2-perception-tflite
uv python install 3.12
uv venv --python 3.12 .venv-convert
uv pip install --python .venv-convert/bin/python -r convert-requirements.txt
.venv-convert/bin/python convert.py            # ~2 min, writes 6 .tflite files
```

Per model it emits `<name>_float32.tflite` (parity baseline) and
`<name>_dynamic_range_quant.tflite` (int8 weights / float I/O — the phone
target), then smoke-compares each against onnxruntime on random input.

What fought back (all handled in `convert.py`, kept here so nobody re-trips):

- **onnx2tf's default `flatbuffer_direct` backend emits broken dynamic-range
  quant**: float32 files were fine, but the DRQ files computed garbage
  (outputs saturated at inf / 3.4e38) for all three models. `convert.py`
  forces `tflite_backend="tf_converter"` (the classic TFLiteConverter path),
  which quantizes correctly and also runs onnx2tf's full per-layer
  ONNX-vs-TF elementwise validation (every layer "Matches").
- **TFLite tensor names cannot be trusted**: the `tf_converter` backend
  reattaches ONNX output names to the *wrong* tensors (observed:
  `det_500m_float32` had name "468" — a (3200,1) score head in ONNX — on a
  (12800,4) bbox tensor). Both the smoke check and the runtime adapter map
  outputs **by unique static shape**, never by name. All nine SCRFD output
  shapes (and the single YOLOX/ArcFace outputs) are unique, so the mapping is
  deterministic; ambiguity raises instead of guessing.
- **SCRFD's dynamic spatial dims** (`[1,3,'?','?']` in the ONNX graph) were
  the predicted troublemaker but pinned cleanly to 640x640 — exactly the
  letterbox size the desktop decode already uses — via
  `overwrite_input_shape`. Gotcha: onnx2tf applies that overwrite by shelling
  out to the `onnxsim` CLI, which must be on PATH (convert.py prepends the
  venv's bin/; without it the input silently collapsed to `[1,1,1,3]`). The
  runtime adapter also handles a collapsed-dynamic input by
  `resize_tensor_input` as a belt-and-suspenders fallback.
- **ArcFace's dynamic batch** pinned to 1 the same way. Nothing resisted
  conversion — all three models shipped in both variants.

Sizes: yolox 3.7→1.2 MB, det_500m 2.5→0.8 MB, w600k 13.7→3.7 MB (f32→DRQ);
~5.7 MB total for the phone set vs ~19 MB ONNX.

## Runtime backend

`QUINTACLE_PERCEPTION_BACKEND=tflite` makes `perceive_photo()` run on LiteRT;
unset/`onnx` is byte-for-byte the shipping desktop path. The backend installs
interpreter adapters into `yolo.py`/`faces.py`'s session caches wearing the
onnxruntime-session interface, so **all pre/post-processing (letterboxing,
grid decode, NMS, Umeyama alignment, embedding norm) is the same code on both
backends** — zero duplicated math, parity bugs can only come from weights.

```bash
pip install ai-edge-litert                       # into the core venv
QUINTACLE_PERCEPTION_BACKEND=tflite \
QUINTACLE_TFLITE_VARIANT=dynamic_range_quant \   # default: float32
python -c "..."                                   # any perceive_photo caller
```

Missing litert or missing converted models degrade to the existing
perceive_photo-returns-None-with-one-warning path; enrollment and the people
lens stay stdlib-only and unaffected.

**Why ai-edge-litert** (not `tflite-runtime`): tflite-runtime is abandoned
(last wheels cp311/TF 2.14-era); ai-edge-litert 2.3.0 is Google's maintained
LiteRT package and ships wheels for cp310–cp314 on manylinux x86_64 **and
manylinux_2_27 aarch64** (verified on PyPI 2026-10) — so one library covers
this desktop (Python 3.14) and an aarch64 Linux userland on the phone.

## Parity results (desktop, 2026-10-15)

14 real photos: 11 face photos (same person) + 3 object photos. Backends run
in one process through the full `perceive_photo()` contract; "Subject" was
enrolled from a single ONNX observation (= enrolled on desktop), then matched
by the TFLite passes (= observed on phone). Reproduce with
`core/.venv/bin/python phone/tier2-perception-tflite/parity.py`.

```
photo                  tags onnx==f32  tags onnx==drq  faces o/f/d  IoU f32  IoU drq  cos f32  cos drq  xmatch f32       xmatch drq
-----------------------------------------------------------------------------------------------------------------------------------------
20231201_170914.jpg    yes             yes             1/1/1          1.000    0.994    1.000    0.953    MATCH 1.000      MATCH 0.953
20231201_170916.jpg    yes             yes             1/1/1          1.000    0.998    1.000    0.975    MATCH 0.757      MATCH 0.756
20231201_170918.jpg    yes             yes             1/1/1          1.000    0.996    1.000    0.974    MATCH 0.707      MATCH 0.686
20231201_170919.jpg    yes             yes             1/1/1          1.000    0.999    1.000    0.990    MATCH 0.767      MATCH 0.762
20231201_171034.jpg    yes             yes             1/1/1          1.000    0.997    1.000    0.979    MATCH 0.803      MATCH 0.796
20231201_171036.jpg    yes             yes             1/1/1          1.000    0.995    1.000    0.961    MATCH 0.781      MATCH 0.791
20231201_171037.jpg    yes             yes             1/1/1          1.000    0.994    1.000    0.965    MATCH 0.889      MATCH 0.879
20231201_171038.jpg    yes             yes             1/1/1          1.000    0.996    1.000    0.973    MATCH 0.618      MATCH 0.627
20231202_113505.jpg    yes             yes             1/1/1          1.000    0.994    1.000    0.971    MATCH 0.751      MATCH 0.740
20231202_113506.jpg    yes             yes             1/1/1          1.000    0.995    1.000    0.965    MATCH 0.703      MATCH 0.712
20231202_113507.jpg    yes             yes             1/1/1          1.000    0.997    1.000    0.943    MATCH 0.825      MATCH 0.840
20260908_203808.jpg    yes             yes             0/0/0          -        -        -        -        -                -
20260915_140200.jpg    yes             NO              0/0/0          -        -        -        -        -                -
20260916_104104.jpg    yes             NO              0/0/0          -        -        -        -        -                -

tag mismatches in detail:
  20260915_140200.jpg [drq]: onnx=['book'] tflite=[]
  20260916_104104.jpg [drq]: onnx=['cup', 'person', 'dining table'] tflite=['cup', 'person', 'dining table', 'fork']

photos: 14 (11 face, 3 object)
embedding cosine ONNX vs TFLite-f32:  min 1.0000 / mean 1.0000 (n=11)   [target > 0.98]
embedding cosine ONNX vs TFLite-drq:  min 0.9425 / mean 0.9680 (n=11)
face box IoU   ONNX vs TFLite-f32:  min 1.0000 / mean 1.0000 (n=11)
face box IoU   ONNX vs TFLite-drq:  min 0.9937 / mean 0.9959 (n=11)
cross-backend enrollment (tflite-f32 vs ONNX-enrolled face): 11/11 face photos matched 'Subject' @ 0.55
cross-backend enrollment (tflite-drq vs ONNX-enrolled face): 11/11 face photos matched 'Subject' @ 0.55
mean perceive_photo ms/photo: onnx=361, tflite-f32=138, tflite-drq=132
```

Readings:

- **float32 conversion is exact for this purpose**: cosine 1.0000 (4 d.p.)
  and identical boxes/tags on every photo — far above the 0.98 target.
- **int8 dynamic-range drift is real but harmless where it matters**: face
  embeddings land at cosine 0.943–0.990 vs ONNX, boxes barely move
  (IoU ≥ 0.994), and YOLO tags only wobbled on 2 of 14 photos (one missed
  'book', one extra 'fork') — both marginal detections near the 0.35
  confidence floor.
- **The sync story holds**: a face enrolled from a desktop/ONNX embedding is
  matched by the TFLite backend on *different* photos of the same person,
  11/11 at the 0.55 threshold, with the worst score 0.618 (f32) / 0.627
  (drq) — the DRQ scores track f32 within ~0.02, so quantization eats almost
  none of the threshold margin. Desktop-enrolls → phone-matches works.
- Bonus: LiteRT+XNNPACK is ~2.6x faster than onnxruntime CPU here.

## On-device install (honest assessment — no device has run this)

- **Stock Termux: `pip install ai-edge-litert` will NOT work.** PyPI has only
  `manylinux` (glibc) aarch64 wheels; Termux's Python is bionic-libc
  (`linux-android` platform tags), and there is no Termux/TUR build of
  LiteRT. No amount of pip flags fixes a libc mismatch.
- **Workable route A — proot/chroot glibc distro inside Termux**
  (`proot-distro install debian`, then a normal venv there): manylinux
  aarch64 wheels install as-is; the whole core (Python 3.12+ available in
  Debian) runs unchanged. Cost: proot syscall overhead and — critically —
  **no NNAPI from inside proot**; this route is CPU/XNNPACK only. Given the
  measured desktop speeds (~130 ms/photo on CPU) that is already usable.
- **Workable route B — the APK native module** (the real NPU path, per
  `docs/local-vision-phone-plan.md`): the same .tflite files loaded through
  LiteRT's Kotlin/NDK API with the NNAPI (or Qualcomm QNN) delegate; the
  Python core talks to it over localhost exactly like the planned
  narrate/extract/embed calls. The models this tier produces are the
  artifact that module consumes.
- Model transport: the 6 files in `~/.quintacle/perception/models/tflite/`
  are plain files under the data dir; the existing LAN sync (or a one-time
  copy) moves them. Nothing phones home — conversion and inference are fully
  offline.

## Delegate activation (wired, desktop no-op)

`QUINTACLE_TFLITE_DELEGATE=<name-or-.so-path>` is passed to
`ai_edge_litert.interpreter.load_delegate()` at interpreter construction. On
this desktop any value warns once and falls back to CPU — NNAPI/QNN delegate
libraries only exist on devices, so **only a device can prove the delegate
path**. Expected device values: `libnnapi_external_delegate.so` /
vendor QNN delegate `.so` from the Qualcomm AI SDK (TBD against the actual
S25U image; benchmark with a stock TFLite benchmarker first, per the phone
plan).

## Device-pending unknowns

1. NNAPI/QNN delegate actually loading + which ops fall back to CPU on the
   Hexagon (SCRFD's exp/div-heavy decode tail is the usual suspect — but the
   decode is in numpy on our side; only the conv backbones go to the NPU).
2. Whether DRQ (int8 weights, float activations) even engages the NPU, or
   full integer quant (`-oiqt`, needs a calibration set) is required — the
   NaviGatr lineage says full-int is what Edge-TPU-class hardware wanted.
3. Real per-photo latency/thermals on the phone (desktop numbers above are
   x86 XNNPACK, only a floor-sanity signal).
4. proot CPU route performance on the actual phone.

## Tests

`core/tests/test_backend_tflite.py` — same two-tier skip style as
`test_perception.py`: env/default/degradation tests always run; interpreter
tests skip without `ai-edge-litert` + converted models. Verified green both
ways: full venv 305 passed / 0 skipped; minimal venv (requirements.txt only)
296 passed / 9 skipped (4 pre-existing perception model-tier + 5 from this
tier).
