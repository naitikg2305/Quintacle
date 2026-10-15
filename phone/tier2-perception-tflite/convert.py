#!/usr/bin/env python
"""ONNX -> TFLite conversion for Quintacle's perception models (Tier 2).

Converts the three ONNX models the desktop perception lane runs
(core/quintacle_core/perception/) into TFLite for the phone's LiteRT/NNAPI
path, producing for each model:

- <name>_float32.tflite            parity baseline (should match ONNX ~exactly)
- <name>_dynamic_range_quant.tflite  int8 dynamic-range weights, float I/O —
                                     the phone target (NaviGatr lineage: the
                                     same int8-TFLite-on-accelerator shape
                                     that ran on the Pi 5 + Coral).

Outputs land in `<models dir>/tflite/` (default
`~/.quintacle/perception/models/tflite/`) — NEVER in the repo.

Run this in the dedicated conversion venv (Python 3.12 — onnx2tf/tensorflow
do not support 3.14; see convert-requirements.txt):

    cd phone/tier2-perception-tflite
    uv python install 3.12
    uv venv --python 3.12 .venv-convert
    uv pip install --python .venv-convert/bin/python -r convert-requirements.txt
    .venv-convert/bin/python convert.py

Model-specific notes:
- yolox_nano: static (1,3,416,416), single (1,3549,85) output — easy case.
- det_500m (SCRFD): dynamic spatial dims ('?','?') in the ONNX graph. TFLite
  wants static shapes, so we pin them to 640x640 — exactly the letterbox size
  the desktop decode uses (_DET_INPUT_SIZE in faces.py), so behavior matches.
- w600k_mbf (ArcFace): dynamic batch -> pinned to 1.

The converter transposes inputs NCHW -> NHWC (TFLite's native layout); the
runtime adapter in core/quintacle_core/perception/backend_tflite.py undoes
that at the boundary so the shared numpy pre/post-processing stays identical.
`copy_onnx_input_output_names_to_tflite` keeps ONNX tensor names on the
TFLite tensors, which the adapter uses to return outputs in ONNX order
(shape-based fallback exists; all output shapes are unique per model).

Each conversion runs onnx2tf's elementwise ONNX-vs-TF output check
(check_onnx_tf_outputs_elementwise_close_full) so a silently-broken graph
fails loudly here, not in the parity harness.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

# Mirrors core/quintacle_core/perception/download.py — kept inline because the
# conversion venv (py3.12, no pydantic) does not install quintacle_core.
YOLOX_NANO_URL = "https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_nano.onnx"
BUFFALO_SC_URL = "https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_sc.zip"

# (onnx filename, overwrite_input_shape or None)
MODELS = (
    ("yolox_nano.onnx", None),  # already static (1,3,416,416)
    ("det_500m.onnx", ["input.1:1,3,640,640"]),  # pin dynamic H,W to the desktop letterbox size
    ("w600k_mbf.onnx", ["input.1:1,3,112,112"]),  # pin dynamic batch to 1
)

VARIANTS = ("float32", "dynamic_range_quant")


def models_dir() -> Path:
    override = os.environ.get("QUINTACLE_PERCEPTION_MODELS_DIR")
    if override:
        return Path(override)
    data_dir = Path(os.environ.get("QUINTACLE_DATA_DIR", Path.home() / ".quintacle"))
    return data_dir / "perception" / "models"


def _download(url: str, dest: Path) -> None:
    print(f"downloading {url} -> {dest}")
    tmp = dest.with_suffix(dest.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "Quintacle/1.0"})
    with urllib.request.urlopen(request, timeout=120) as response, open(tmp, "wb") as out:
        shutil.copyfileobj(response, out)
    tmp.replace(dest)


def ensure_onnx(name: str) -> Path:
    directory = models_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    if path.is_file():
        return path
    if name == "yolox_nano.onnx":
        _download(YOLOX_NANO_URL, path)
        return path
    zip_path = directory / "buffalo_sc.zip"
    if not zip_path.is_file():
        _download(BUFFALO_SC_URL, zip_path)
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.namelist():
            base = Path(member).name
            if member.endswith(".onnx") and not (directory / base).is_file():
                with archive.open(member) as src, open(directory / base, "wb") as out:
                    shutil.copyfileobj(src, out)
    if not path.is_file():
        raise FileNotFoundError(f"{name} not found inside {zip_path}")
    return path


def convert_one(onnx_path: Path, overwrite_input_shape: list[str] | None, out_dir: Path) -> list[Path]:
    import onnx2tf

    # onnx2tf shells out to `onnxsim` (that's also how overwrite_input_shape
    # gets baked); when convert.py is invoked as .venv-convert/bin/python the
    # venv's bin/ isn't on PATH, so put it there.
    venv_bin = str(Path(sys.executable).parent)
    if venv_bin not in os.environ.get("PATH", "").split(os.pathsep):
        os.environ["PATH"] = venv_bin + os.pathsep + os.environ.get("PATH", "")

    stem = onnx_path.stem
    produced: list[Path] = []
    with tempfile.TemporaryDirectory(prefix=f"onnx2tf_{stem}_") as tmp:
        kwargs: dict = dict(
            input_onnx_file_path=str(onnx_path),
            output_folder_path=tmp,
            copy_onnx_input_output_names_to_tflite=True,
            output_dynamic_range_quantized_tflite=True,
            # onnx2tf 2.6.x's default "flatbuffer_direct" backend emits
            # float32 fine but its dynamic-range-quant files computed garbage
            # (inf / float32-max outputs) for all three of these models —
            # verified 2026-10 via smoke_check. The classic TFLiteConverter
            # path quantizes correctly, so force it.
            tflite_backend="tf_converter",
            # Elementwise ONNX-vs-converted check on dummy data — conversion
            # fails loudly here instead of producing a silently-wrong graph.
            check_onnx_tf_outputs_elementwise_close_full=True,
            verbosity="warn",
        )
        if overwrite_input_shape:
            kwargs["overwrite_input_shape"] = overwrite_input_shape
        onnx2tf.convert(**kwargs)
        for variant in VARIANTS:
            src = Path(tmp) / f"{stem}_{variant}.tflite"
            if not src.is_file():
                raise FileNotFoundError(f"onnx2tf did not produce {src.name}")
            dest = out_dir / src.name
            shutil.copy2(src, dest)
            produced.append(dest)
            print(f"  wrote {dest} ({dest.stat().st_size / 1e6:.1f} MB)")
    return produced


def smoke_check(tflite_path: Path, onnx_path: Path) -> str:
    """Run both runtimes on the same random input; report max-abs diff.
    float32 should be ~1e-4-class; dynamic-range quant will drift more."""
    import numpy as np
    import onnxruntime as ort
    from ai_edge_litert.interpreter import Interpreter

    sess = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    onnx_input = sess.get_inputs()[0]
    shape = [1 if not isinstance(v, int) else v for v in onnx_input.shape]
    if "det_500m" in onnx_path.name:
        shape = [1, 3, 640, 640]
    rng = np.random.default_rng(0)
    blob = rng.uniform(0, 255, size=shape).astype(np.float32)
    onnx_outs = sess.run(None, {onnx_input.name: blob})

    interp = Interpreter(model_path=str(tflite_path))
    detail = interp.get_input_details()[0]
    feed = (
        np.ascontiguousarray(blob.transpose(0, 2, 3, 1))
        if (int(detail["shape"][-1]) == 3 and shape[1] == 3)
        else blob
    )
    if tuple(detail["shape"]) != feed.shape:
        # dynamic dims collapse to 1 in the flatbuffer — resize at load time
        interp.resize_tensor_input(detail["index"], list(feed.shape))
    interp.allocate_tensors()
    interp.set_tensor(detail["index"], feed)
    interp.invoke()
    # Map tflite outputs to ONNX outputs BY SHAPE, not by name: the
    # tf_converter backend reattaches ONNX tensor names to the wrong outputs
    # (observed: det_500m_float32 name "468" on a (12800,4) tensor). Every
    # output shape is unique in all three perception models, so shape mapping
    # is deterministic; rank-3 channel-last transposes are accepted too.
    lite_by_shape: dict[tuple, list] = {}
    for od in interp.get_output_details():
        arr = interp.get_tensor(od["index"])
        lite_by_shape.setdefault(arr.shape, []).append(arr)
    diffs = []
    for onnx_out, meta in zip(onnx_outs, sess.get_outputs()):
        candidates = lite_by_shape.get(onnx_out.shape, [])
        if not candidates and onnx_out.ndim == 3:
            transposed = (onnx_out.shape[0], onnx_out.shape[2], onnx_out.shape[1])
            candidates = [c.transpose(0, 2, 1) for c in lite_by_shape.get(transposed, [])]
        if len(candidates) != 1:
            return f"SHAPE MAP AMBIGUOUS for {meta.name} {onnx_out.shape}: {len(candidates)} candidates"
        diffs.append(float(np.abs(onnx_out - candidates[0]).max()))
    return f"max|diff| per output: {['%.4g' % d for d in diffs]}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", choices=[m[0] for m in MODELS], help="convert a single model")
    args = parser.parse_args()

    out_dir = models_dir() / "tflite"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"output dir: {out_dir}")

    failures: list[str] = []
    failures_from_smoke: list[str] = []
    for name, overwrite in MODELS:
        if args.only and name != args.only:
            continue
        onnx_path = ensure_onnx(name)
        print(f"\n=== {name} ===")
        try:
            produced = convert_one(onnx_path, overwrite, out_dir)
        except Exception as exc:  # noqa: BLE001 — report and keep going: partial delivery beats none
            print(f"  CONVERSION FAILED: {exc!r}")
            failures.append(f"{name}: {exc!r}")
            continue
        for tflite_path in produced:
            try:
                verdict = smoke_check(tflite_path, onnx_path)
            except Exception as exc:  # noqa: BLE001
                verdict = f"SMOKE FAILED: {exc!r}"
            print(f"  smoke {tflite_path.name}: {verdict}")
            if "FAILED" in verdict or "MISMATCH" in verdict or "NO NAME" in verdict:
                failures_from_smoke.append(f"{tflite_path.name}: {verdict}")

    if failures or failures_from_smoke:
        print("\nFAILED:")
        for f in failures + failures_from_smoke:
            print(f"  - {f}")
        return 1
    print("\nall conversions OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
