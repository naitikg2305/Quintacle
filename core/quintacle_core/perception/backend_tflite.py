"""TFLite (LiteRT) runtime backend for the perception lane — the phone path.

Selected with QUINTACLE_PERCEPTION_BACKEND=tflite (default "onnx": nothing
here runs and the ONNX path is byte-for-byte untouched). Runs the SAME models
as the ONNX path, converted by phone/tier2-perception-tflite/convert.py into
`<models dir>/tflite/` — there is no auto-download for these: they are build
artifacts, produced once on a desktop and shipped to the device.

Zero duplicated math. yolo.py and faces.py already route every model call
through a cached session object whose only used surface is
`session.get_inputs()[0].name` and `session.run(None, {name: blob})` — the
onnxruntime InferenceSession interface. This module provides _LiteRTSession,
a LiteRT interpreter wearing exactly that interface (transposing the blob to
TFLite's NHWC at the boundary and returning outputs in ONNX order), and
installs instances into yolo/faces' session caches when the env selects
tflite. All preprocessing, decode, NMS, alignment and embedding code runs
unchanged — which is the point: parity bugs can only come from the converted
weights, never from a second copy of the pipeline.

Runtime library: ai-edge-litert (Google's maintained LiteRT Python package).
Chosen over the abandoned tflite-runtime because ai-edge-litert ships current
wheels for cp310-cp314 including manylinux aarch64 (tflite-runtime stopped at
cp311/TF2.14). On-device honesty: manylinux wheels do NOT install in stock
Termux (bionic libc) — they do install in a proot/chroot glibc distro inside
Termux, or the interpreter runs inside the APK via LiteRT's native API. See
phone/tier2-perception-tflite/README.md.

Env knobs:
- QUINTACLE_PERCEPTION_BACKEND=onnx|tflite  (default onnx)
- QUINTACLE_TFLITE_VARIANT=float32|dynamic_range_quant  (default float32;
  dynamic_range_quant is the phone target — int8 weights, float I/O)
- QUINTACLE_TFLITE_DELEGATE=<name-or-.so-path>  wires a LiteRT delegate
  (NNAPI/QNN/...) into the interpreter. On desktop this is a NO-OP beyond a
  one-time warning: desktop LiteRT has no NNAPI/Hexagon, and only a real
  device can prove a delegate. Load failures degrade to CPU, never crash.

Heavy imports (numpy, ai_edge_litert) are lazy; a selected-but-missing
tflite stack makes perception_available() False, which flows into the
existing perceive_photo -> None-with-one-warning path.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from .download import FACE_DETECT_MODEL, FACE_EMBED_MODEL, YOLO_MODEL
from .storage import models_dir

logger = logging.getLogger(__name__)

BACKEND_ENV = "QUINTACLE_PERCEPTION_BACKEND"
VARIANT_ENV = "QUINTACLE_TFLITE_VARIANT"
DELEGATE_ENV = "QUINTACLE_TFLITE_DELEGATE"

_VARIANTS = ("float32", "dynamic_range_quant")

# ONNX graph I/O names per model, in ONNX output order — the contract
# yolo.py/faces.py's post-processing indexes by. The input name is what the
# pipelines feed by; output names document the order (resolution itself is by
# unique shape — see _LiteRTSession._resolve_outputs).
_ONNX_IO: dict[str, tuple[str, tuple[str, ...]]] = {
    YOLO_MODEL: ("images", ("output",)),
    FACE_DETECT_MODEL: (
        "input.1",
        ("443", "468", "493", "446", "471", "496", "449", "474", "499"),
    ),
    FACE_EMBED_MODEL: ("input.1", ("516",)),
}

_warned_delegate = False


def backend_name() -> str:
    return (os.environ.get(BACKEND_ENV) or "onnx").strip().lower() or "onnx"


def selected() -> bool:
    return backend_name() == "tflite"


def variant() -> str:
    value = (os.environ.get(VARIANT_ENV) or "float32").strip() or "float32"
    if value not in _VARIANTS:
        logger.warning("%s=%r unknown — using float32 (known: %s)", VARIANT_ENV, value, _VARIANTS)
        return "float32"
    return value


def tflite_models_dir() -> Path:
    return models_dir() / "tflite"


def model_path(onnx_name: str) -> Path:
    stem = Path(onnx_name).stem
    return tflite_models_dir() / f"{stem}_{variant()}.tflite"


def available() -> bool:
    """True when the LiteRT stack can actually serve perceive_photo: deps
    importable AND all three converted models present for the active variant.
    (Unlike ONNX weights, .tflite files never auto-download — convert.py
    builds them.)"""
    try:
        import numpy  # noqa: F401
        from ai_edge_litert.interpreter import Interpreter  # noqa: F401
    except ImportError:
        return False
    return all(model_path(m).is_file() for m in (YOLO_MODEL, FACE_DETECT_MODEL, FACE_EMBED_MODEL))


def _load_delegates() -> list:
    """QUINTACLE_TFLITE_DELEGATE -> [delegate] | []. Desktop reality: this is
    documentation-wired only — NNAPI/QNN .so files exist on devices, not here,
    so failures warn once and fall back to CPU."""
    global _warned_delegate
    spec = (os.environ.get(DELEGATE_ENV) or "").strip()
    if not spec:
        return []
    exc: Exception | None = None
    if ("/" in spec or spec.endswith(".so")) and not Path(spec).exists():
        # don't hand a missing path to load_delegate — its half-constructed
        # Delegate object raises again from __del__ (ai-edge-litert bug)
        exc = FileNotFoundError(spec)
    else:
        try:
            from ai_edge_litert.interpreter import load_delegate

            return [load_delegate(spec)]
        except Exception as load_exc:  # noqa: BLE001 — delegate failure means CPU, never a crash
            exc = load_exc
    if not _warned_delegate:
        logger.warning(
            "%s=%r could not be loaded (%s) — running TFLite on CPU. "
            "NNAPI/QNN delegates only exist on a real device.",
            DELEGATE_ENV,
            spec,
            exc,
        )
        _warned_delegate = True
    return []


class _LiteRTSession:
    """A LiteRT Interpreter wearing onnxruntime InferenceSession's minimal
    interface — get_inputs()[0].name and run(None, {name: blob}) — so the
    shared numpy pipeline in yolo.py/faces.py runs on it unchanged.

    Boundary translation only (all verified against the real conversions):
    - input: ONNX blobs are NCHW; onnx2tf-converted models want NHWC ->
      transpose when the model's input has channels-last. If the flatbuffer
      kept a dynamic dim collapsed to 1 (det_500m's H,W when the static pin
      didn't bake), resize_tensor_input before the first invoke.
    - outputs: returned as a list in ONNX output order, resolved by unique
      static shape (see _resolve_outputs for why names can't be trusted);
      rank-3 outputs that onnx2tf left channel-last (yolox's (1,85,3549) vs
      ONNX's (1,3549,85)) are transposed back.
    """

    class _Input:
        __slots__ = ("name",)

        def __init__(self, name: str):
            self.name = name

    def __init__(self, onnx_name: str):
        import numpy as np
        from ai_edge_litert.interpreter import Interpreter

        self._np = np
        path = model_path(onnx_name)
        if not path.is_file():
            raise FileNotFoundError(
                f"{path} missing — run phone/tier2-perception-tflite/convert.py first"
            )
        self._interpreter = Interpreter(
            model_path=str(path), experimental_delegates=_load_delegates()
        )
        input_name, output_names = _ONNX_IO[onnx_name]
        self._onnx_input = self._Input(input_name)
        detail = self._interpreter.get_input_details()[0]
        self._input_index = detail["index"]
        self._nhwc = len(detail["shape"]) == 4 and int(detail["shape"][-1]) == 3
        self._allocated_shape: tuple[int, ...] | None = None
        self._onnx_shapes = _EXPECTED_OUTPUT_SHAPES[input_name, len(output_names)]
        self._output_indices = self._resolve_outputs(output_names)

    def _resolve_outputs(self, onnx_order: tuple[str, ...]) -> list[int]:
        """Map ONNX output order -> tflite tensor indices BY SHAPE. Names are
        deliberately not trusted: onnx2tf's tf_converter backend reattaches
        the ONNX tensor names to the WRONG outputs (observed on
        det_500m_float32: name "468" on a (12800,4) tensor). Every output
        shape in these three models is unique — checked here, not assumed —
        so shape mapping is deterministic. Rank-3 channel-last transposes
        (yolox under the flatbuffer_direct backend: (1,85,3549)) also match;
        run() transposes those back."""
        details = self._interpreter.get_output_details()
        shape_index: dict[tuple[int, ...], int | None] = {}
        for d in details:
            s = tuple(int(v) for v in d["shape"])
            keys = {s, (s[0], s[2], s[1])} if len(s) == 3 else {s}
            for key in keys:
                shape_index[key] = None if key in shape_index else d["index"]  # None = ambiguous
        indices = []
        for shape in self._onnx_shapes:
            index = shape_index.get(shape)
            if index is None:
                raise RuntimeError(
                    f"cannot map tflite outputs: shape {shape} missing or ambiguous "
                    f"(available: {[tuple(int(v) for v in d['shape']) for d in details]})"
                )
            indices.append(index)
        return indices

    def get_inputs(self):
        return [self._onnx_input]

    def run(self, _output_names, feeds: dict):
        np = self._np
        blob = np.ascontiguousarray(next(iter(feeds.values())), dtype=np.float32)
        if self._nhwc:
            blob = np.ascontiguousarray(blob.transpose(0, 2, 3, 1))
        if self._allocated_shape != blob.shape:
            detail_shape = tuple(int(v) for v in self._interpreter.get_input_details()[0]["shape"])
            if detail_shape != blob.shape:
                # dynamic ONNX dims collapse to 1 in the flatbuffer (det_500m
                # H,W) — resize to the real letterbox size before allocating
                self._interpreter.resize_tensor_input(self._input_index, list(blob.shape))
            self._interpreter.allocate_tensors()
            self._allocated_shape = blob.shape
        self._interpreter.set_tensor(self._input_index, blob)
        self._interpreter.invoke()
        outputs = []
        for index, onnx_shape in zip(self._output_indices, self._onnx_shapes):
            arr = np.array(self._interpreter.get_tensor(index))  # copy: get_tensor returns a view
            if arr.shape != onnx_shape and arr.ndim == 3 and arr.transpose(0, 2, 1).shape == onnx_shape:
                arr = np.ascontiguousarray(arr.transpose(0, 2, 1))  # undo channel-last output layout
            outputs.append(arr)
        return outputs


# Shape fallback table, keyed by (onnx input name, output count) — matches the
# fixed shapes convert.py pins (det_500m at 640x640, batch 1 everywhere).
_EXPECTED_OUTPUT_SHAPES = {
    ("images", 1): [(1, 3549, 85)],
    ("input.1", 9): [
        (12800, 1), (3200, 1), (800, 1),
        (12800, 4), (3200, 4), (800, 4),
        (12800, 10), (3200, 10), (800, 10),
    ],
    ("input.1", 1): [(1, 512)],
}

# model path -> adapter, so env flips (variant, backend) rebuild only what
# changed and repeated perceive_photo calls reuse interpreters.
_adapters: dict[Path, _LiteRTSession] = {}


def _adapter(onnx_name: str) -> _LiteRTSession:
    path = model_path(onnx_name)
    if path not in _adapters:
        _adapters[path] = _LiteRTSession(onnx_name)
    return _adapters[path]


def sync_sessions() -> None:
    """Make yolo/faces' session caches agree with the selected backend. Called
    by perceive_photo after the availability check; cheap when nothing
    changed. Writing those caches is this module's whole integration — the
    pipelines themselves never know which runtime they're on."""
    from . import faces, yolo

    if selected():
        yolo._session = _adapter(YOLO_MODEL)
        faces._sessions[FACE_DETECT_MODEL] = _adapter(FACE_DETECT_MODEL)
        faces._sessions[FACE_EMBED_MODEL] = _adapter(FACE_EMBED_MODEL)
    else:
        # back on onnx: drop any LiteRT adapters so ONNX sessions lazy-rebuild
        if isinstance(yolo._session, _LiteRTSession):
            yolo._session = None
        for key in [k for k, s in faces._sessions.items() if isinstance(s, _LiteRTSession)]:
            del faces._sessions[key]
