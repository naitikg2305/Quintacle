"""Tests for the TFLite perception backend switch (backend_tflite.py), in the
same two-tier shape as test_perception.py:

1. Dep-free tier — always runs: env parsing, default-backend behavior, and
   the graceful-None contract when the tflite stack is selected but absent.
2. LiteRT tier — needs ai-edge-litert AND the converted .tflite models
   (built by phone/tier2-perception-tflite/convert.py — never auto-downloaded);
   skips cleanly otherwise, so the base venv stays green.
"""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path

import pytest
from PIL import Image

from quintacle_core import perception
from quintacle_core.perception import backend_tflite
from quintacle_core.perception.download import FACE_DETECT_MODEL, FACE_EMBED_MODEL, YOLO_MODEL


@pytest.fixture()
def perception_home(tmp_path, monkeypatch):
    """Isolated perception state; model weights resolve to the shared cache."""
    monkeypatch.setenv("QUINTACLE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("QUINTACLE_PERCEPTION_MODELS_DIR", str(_shared_models_dir()))
    return tmp_path


def _shared_models_dir() -> Path:
    override = os.environ.get("QUINTACLE_PERCEPTION_MODELS_DIR")
    return Path(override) if override else Path.home() / ".quintacle" / "perception" / "models"


def _have_litert() -> bool:
    try:
        import numpy  # noqa: F401
        from ai_edge_litert.interpreter import Interpreter  # noqa: F401
    except ImportError:
        return False
    return True


def _have_onnx() -> bool:
    try:
        import numpy  # noqa: F401
        import onnxruntime  # noqa: F401
    except ImportError:
        return False
    return True


def _tflite_models_ready() -> bool:
    d = _shared_models_dir() / "tflite"
    return all(
        (d / f"{Path(m).stem}_{variant}.tflite").is_file()
        for m in (YOLO_MODEL, FACE_DETECT_MODEL, FACE_EMBED_MODEL)
        for variant in ("float32", "dynamic_range_quant")
    )


litert_tier = pytest.mark.skipif(
    not (_have_litert() and _tflite_models_ready()),
    reason="needs ai-edge-litert + converted tflite models "
    "(run phone/tier2-perception-tflite/convert.py)",
)


def _photo() -> bytes:
    img = Image.new("RGB", (320, 240), (90, 140, 235))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


# --- tier 1: dep-free ---


def test_default_backend_is_onnx(monkeypatch):
    monkeypatch.delenv(backend_tflite.BACKEND_ENV, raising=False)
    assert backend_tflite.backend_name() == "onnx"
    assert not backend_tflite.selected()
    monkeypatch.setenv(backend_tflite.BACKEND_ENV, "")
    assert backend_tflite.backend_name() == "onnx"


def test_variant_defaults_and_rejects_unknown(monkeypatch):
    monkeypatch.delenv(backend_tflite.VARIANT_ENV, raising=False)
    assert backend_tflite.variant() == "float32"
    monkeypatch.setenv(backend_tflite.VARIANT_ENV, "dynamic_range_quant")
    assert backend_tflite.variant() == "dynamic_range_quant"
    monkeypatch.setenv(backend_tflite.VARIANT_ENV, "int4-nonsense")
    assert backend_tflite.variant() == "float32"


def test_model_path_includes_variant(perception_home, monkeypatch):
    monkeypatch.setenv(backend_tflite.VARIANT_ENV, "dynamic_range_quant")
    path = backend_tflite.model_path(YOLO_MODEL)
    assert path.name == "yolox_nano_dynamic_range_quant.tflite"
    assert path.parent == backend_tflite.tflite_models_dir()


def test_tflite_selected_but_deps_missing_degrades_to_none(perception_home, monkeypatch):
    # Blocking the import (None in sys.modules => ImportError) simulates a
    # venv without ai-edge-litert even when it's installed here.
    monkeypatch.setenv(backend_tflite.BACKEND_ENV, "tflite")
    monkeypatch.setitem(sys.modules, "ai_edge_litert", None)
    monkeypatch.setitem(sys.modules, "ai_edge_litert.interpreter", None)
    assert not backend_tflite.available()
    assert not perception.perception_available()
    assert perception.perceive_photo(_photo(), "image/jpeg") is None


@pytest.mark.skipif(not _have_litert(), reason="needs ai-edge-litert")
def test_tflite_selected_but_models_missing_degrades_to_none(tmp_path, monkeypatch):
    monkeypatch.setenv("QUINTACLE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("QUINTACLE_PERCEPTION_MODELS_DIR", str(tmp_path / "empty-models"))
    monkeypatch.setenv(backend_tflite.BACKEND_ENV, "tflite")
    assert not backend_tflite.available()
    assert not perception.perception_available()
    assert perception.perceive_photo(_photo(), "image/jpeg") is None


def test_onnx_backend_availability_unaffected_by_tflite_env(perception_home, monkeypatch):
    # default backend ignores the tflite stack entirely
    monkeypatch.delenv(backend_tflite.BACKEND_ENV, raising=False)
    monkeypatch.setitem(sys.modules, "ai_edge_litert", None)
    assert perception.perception_available() == _have_onnx()


# --- tier 2: real LiteRT interpreter + converted models ---


@litert_tier
def test_backend_switch_engages_tflite(perception_home, monkeypatch):
    from quintacle_core.perception import yolo

    monkeypatch.setenv(backend_tflite.BACKEND_ENV, "tflite")
    result = perception.perceive_photo(_photo(), "image/jpeg")
    assert result is not None
    assert set(result.model_dump()) == {"tags", "scene", "faces"}
    assert isinstance(yolo._session, backend_tflite._LiteRTSession)


@litert_tier
def test_backend_switch_both_variants_run(perception_home, monkeypatch):
    monkeypatch.setenv(backend_tflite.BACKEND_ENV, "tflite")
    for variant in ("float32", "dynamic_range_quant"):
        monkeypatch.setenv(backend_tflite.VARIANT_ENV, variant)
        assert perception.perceive_photo(_photo(), "image/jpeg") is not None


@litert_tier
@pytest.mark.skipif(not _have_onnx(), reason="needs onnxruntime for the switch-back half")
def test_switch_back_to_onnx_restores_onnx_sessions(perception_home, monkeypatch):
    from quintacle_core.perception import faces, yolo
    from quintacle_core.perception.download import YOLO_MODEL as _Y

    if not (_shared_models_dir() / _Y).is_file():
        pytest.skip("onnx model weights not cached")
    monkeypatch.setenv(backend_tflite.BACKEND_ENV, "tflite")
    assert perception.perceive_photo(_photo(), "image/jpeg") is not None
    assert isinstance(yolo._session, backend_tflite._LiteRTSession)

    monkeypatch.setenv(backend_tflite.BACKEND_ENV, "onnx")
    assert perception.perceive_photo(_photo(), "image/jpeg") is not None
    assert not isinstance(yolo._session, backend_tflite._LiteRTSession)
    assert not any(isinstance(s, backend_tflite._LiteRTSession) for s in faces._sessions.values())


@litert_tier
def test_bogus_delegate_degrades_to_cpu_not_crash(perception_home, monkeypatch):
    # Desktop reality: NNAPI/QNN delegates only exist on devices. A set-but-
    # unloadable delegate must warn and run on CPU, never raise.
    monkeypatch.setenv(backend_tflite.BACKEND_ENV, "tflite")
    monkeypatch.setenv(backend_tflite.DELEGATE_ENV, "/nonexistent/libnnapi_delegate.so")
    backend_tflite._adapters.clear()  # force fresh interpreters so the delegate path runs
    monkeypatch.setattr(backend_tflite, "_warned_delegate", False)
    assert perception.perceive_photo(_photo(), "image/jpeg") is not None
    backend_tflite._adapters.clear()  # don't leak delegate-tainted adapters to other tests
