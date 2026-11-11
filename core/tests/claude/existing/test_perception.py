"""Perception tests, in two tiers:

1. Dep-free tier — always runs, even in a venv without onnxruntime/numpy
   (requirements.txt only): storage/enrollment, matching math, scene
   heuristics, and the graceful-None contract when deps are missing.
2. Model tier — needs the optional perception deps AND the ~19 MB of model
   weights; skips cleanly otherwise. Weights download on first use only when
   QUINTACLE_PERCEPTION_ALLOW_DOWNLOAD=1 (or are already cached), so a plain
   offline test run never hits the network.

Honest limits: synthetic PIL-drawn images don't contain real COCO objects or
real faces, so the model tier validates plumbing, shapes and determinism —
detection/recognition QUALITY can only be judged on real photos.
"""

from __future__ import annotations

import io
import math
import os
import sys
from pathlib import Path

import pytest
from PIL import Image

from quintacle_core import perception
from quintacle_core.perception import FACE_MATCH_THRESHOLD, scene, storage
from quintacle_core.perception.download import FACE_DETECT_MODEL, FACE_EMBED_MODEL, YOLO_MODEL


@pytest.fixture()
def perception_home(tmp_path, monkeypatch):
    """Isolated perception state (embeddings/profiles in tmp), while model
    weights still resolve to one shared cache dir so the model tier never
    re-downloads per test."""
    monkeypatch.setenv("QUINTACLE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("QUINTACLE_PERCEPTION_MODELS_DIR", str(_shared_models_dir()))
    return tmp_path


def _shared_models_dir() -> Path:
    override = os.environ.get("QUINTACLE_PERCEPTION_MODELS_DIR")
    return Path(override) if override else Path.home() / ".quintacle" / "perception" / "models"


def _have_deps() -> bool:
    try:
        import numpy  # noqa: F401
        import onnxruntime  # noqa: F401
    except ImportError:
        return False
    return True


def _models_ready() -> bool:
    d = _shared_models_dir()
    return all((d / m).is_file() for m in (YOLO_MODEL, FACE_DETECT_MODEL, FACE_EMBED_MODEL))


model_tier = pytest.mark.skipif(
    not (_have_deps() and (_models_ready() or os.environ.get("QUINTACLE_PERCEPTION_ALLOW_DOWNLOAD") == "1")),
    reason="needs perception deps (core/perception-requirements.txt) + model weights "
    "(cached, or QUINTACLE_PERCEPTION_ALLOW_DOWNLOAD=1 to fetch ~19 MB once)",
)


def _synthetic_photo(exif_hour: int | None = 14) -> bytes:
    """A sky-over-grass JPEG with an EXIF timestamp — enough for the scene
    heuristics; deliberately NOT expected to contain detectable objects."""
    img = Image.new("RGB", (320, 240))
    for y in range(240):
        for x in range(0, 320, 8):
            color = (90, 140, 235) if y < 90 else (70, 150, 60)
            for dx in range(8):
                img.putpixel((x + dx, y), color)
    exif = Image.Exif()
    if exif_hour is not None:
        exif[306] = f"2026:06:01 {exif_hour:02d}:30:00"  # DateTime
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif)
    return buf.getvalue()


# --- tier 1: no heavy deps needed ---


def test_perceive_photo_returns_none_when_deps_missing(perception_home, monkeypatch):
    # Blocking the import (None in sys.modules => ImportError) simulates the
    # no-deps venv even when deps are installed here.
    monkeypatch.setitem(sys.modules, "onnxruntime", None)
    assert perception.perceive_photo(_synthetic_photo(), "image/jpeg") is None


def test_enroll_and_lens_people_round_trip(perception_home):
    embedding_id = storage.save_embedding([0.6, 0.8], {"mime": "image/jpeg", "sha256": "ab" * 32})
    assert perception.lens_people() == []
    perception.enroll_face(embedding_id, "Naitik")
    assert perception.lens_people() == ["Naitik"]
    # enrolling the same id twice doesn't duplicate; a second person sorts in
    other = storage.save_embedding([1.0, 0.0], {"mime": "image/jpeg", "sha256": "cd" * 32})
    perception.enroll_face(embedding_id, "Naitik")
    perception.enroll_face(other, "Alex")
    assert perception.lens_people() == ["Alex", "Naitik"]
    assert storage._load_profiles()["Naitik"] == [embedding_id]


def test_enroll_unknown_embedding_id_raises(perception_home):
    with pytest.raises(FileNotFoundError):
        perception.enroll_face("deadbeef", "Nobody")


def test_embedding_vectors_stay_inside_perception_dir(perception_home):
    embedding_id = storage.save_embedding([0.1] * 8, {"mime": "image/png", "sha256": "ef" * 32})
    path = storage.embeddings_dir() / f"{embedding_id}.json"
    assert path.is_file()
    assert path.is_relative_to(perception_home / "perception")
    stored = storage.load_embedding(embedding_id)
    assert stored["vector"] == pytest.approx([0.1] * 8)
    # ids that try to smuggle a path never resolve
    assert storage.load_embedding("../profiles") is None


def test_best_match_picks_highest_cosine_and_threshold_separates_unknown(perception_home):
    a = storage.save_embedding([1.0, 0.0, 0.0], {})
    b = storage.save_embedding([0.0, 1.0, 0.0], {})
    perception.enroll_face(a, "Ana")
    perception.enroll_face(b, "Ben")

    name, score = storage.best_match([0.9, 0.1, 0.0])
    assert name == "Ana"
    assert score == pytest.approx(0.9 / math.sqrt(0.82), rel=1e-6)
    assert score >= FACE_MATCH_THRESHOLD  # would match

    name2, score2 = storage.best_match([0.5, 0.5, math.sqrt(0.5) * 10])  # mostly orthogonal
    assert score2 < FACE_MATCH_THRESHOLD  # would stay unknown


def test_best_match_none_when_nobody_enrolled(perception_home):
    assert storage.best_match([1.0, 0.0]) is None


def test_scene_daylight_outdoor_and_brightness():
    img = Image.open(io.BytesIO(_synthetic_photo(exif_hour=14)))
    result = scene.analyze_scene(img)
    assert result["daylight"] is True
    assert result["outdoor_hint"] is True  # blue top strip reads as sky
    assert 0.0 < result["brightness"] < 1.0

    night = Image.open(io.BytesIO(_synthetic_photo(exif_hour=23)))
    assert scene.analyze_scene(night)["daylight"] is False

    no_exif = Image.open(io.BytesIO(_synthetic_photo(exif_hour=None)))
    assert scene.analyze_scene(no_exif)["daylight"] is None

    indoor_dark = Image.new("RGB", (100, 100), (40, 30, 30))
    result_dark = scene.analyze_scene(indoor_dark)
    assert result_dark["outdoor_hint"] is None  # no sky visible => unknown, not False
    assert result_dark["brightness"] < 0.2


# --- tier 2: real models (plumbing/shape/determinism, not accuracy) ---


@model_tier
def test_perceive_photo_full_pass_on_synthetic_image(perception_home):
    data = _synthetic_photo()
    result = perception.perceive_photo(data, "image/jpeg")
    assert result is not None
    dumped = result.model_dump()
    assert set(dumped) == {"tags", "scene", "faces"}
    assert isinstance(dumped["tags"], list)
    assert dumped["scene"]["daylight"] is True
    for face in result.faces:
        assert len(face.box) == 4
        assert all(0.0 <= v <= 1.0 for v in face.box)
        # every observation persisted an enrollable embedding
        assert storage.load_embedding(face.embedding_id) is not None


@model_tier
def test_perceive_photo_is_deterministic(perception_home):
    data = _synthetic_photo()
    first = perception.perceive_photo(data, "image/jpeg")
    second = perception.perceive_photo(data, "image/jpeg")
    assert first.tags == second.tags
    assert first.scene == second.scene
    assert [f.box for f in first.faces] == [f.box for f in second.faces]


@model_tier
def test_perceive_photo_rejects_non_image_bytes(perception_home):
    with pytest.raises(ValueError):
        perception.perceive_photo(b"definitely not an image", "image/jpeg")


@model_tier
def test_asset_perceive_endpoint_round_trip(perception_home, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from quintacle_core.nodes.kb import api as kb_api

    kb_api.init_store(perception_home / "kb")
    app = FastAPI()
    app.include_router(kb_api.router)
    client = TestClient(app)

    kb_api.get_store().write("Media", "Backyard", "a photo")
    asset_path = kb_api.get_store().save_asset("Media", "backyard.jpg", _synthetic_photo())

    response = client.post("/kb/asset/perceive", json={"folder": "Media", "path": asset_path})
    assert response.status_code == 200
    body = response.json()
    assert body["path"] == asset_path
    assert set(body["perception"]) == {"tags", "scene", "faces"}

    missing = client.post("/kb/asset/perceive", json={"folder": "Media", "path": "assets/nope.jpg"})
    assert missing.status_code == 404
    not_image = client.post("/kb/asset/perceive", json={"folder": "Media", "path": "assets/nope.stl"})
    assert not_image.status_code == 400
