"""Local perception — "the people lens": YOLO object tags, face
detection/recognition with enrollment, and cheap deterministic scene
attributes. Everything runs on-device (onnxruntime CPU); NOTHING here calls
an LLM or any cloud API — the only network traffic ever is the one-time model
weight download (see download.py).

Contract (consumed by the auto-journal side — do not rename):

    perceive_photo(data, mime)  -> PerceptionResult | None  (None = deps missing)
    enroll_face(embedding_id, person_name)
    lens_people()               -> list[str]

Dependency discipline: the heavy deps (onnxruntime, numpy) live in
core/perception-requirements.txt, NOT core/requirements.txt. This module
imports clean at all times; heavy imports happen lazily inside perceive_photo,
which degrades to None (one warning log) when they're absent. enroll_face and
lens_people are stdlib-only and always work.

Privacy: face embedding VECTORS are persisted only under
`<data dir>/perception/` and never leave it (see storage.py). Everything that
flows onward — proposal payloads, journal, graph — carries person NAMES and
opaque embedding_ids only.
"""

from __future__ import annotations

import hashlib
import io
import logging

from pydantic import BaseModel

from . import storage

logger = logging.getLogger(__name__)

# Cosine-similarity floor for calling a face a known person rather than
# unknown. FaceNet/ArcFace-family convention: same-person pairs land well
# above ~0.5, different people rarely exceed ~0.3; 0.55 favors "unknown" over
# a false name (a wrong auto-name is worse than asking the user to confirm).
FACE_MATCH_THRESHOLD = 0.55


class FaceObservation(BaseModel):
    box: list[float]  # x, y, w, h as 0-1 fractions of the image
    embedding_id: str  # persisted at observation time — enrollable later without re-processing
    match: dict | None = None  # {"person_name": str, "score": float} | None (None = unknown face)


class PerceptionResult(BaseModel):
    tags: list[str]  # deduped YOLO object labels, best-confidence first
    scene: dict  # {"daylight": bool|None, "outdoor_hint": bool|None, "brightness": float}
    faces: list[FaceObservation]


_warned_deps_missing = False


def perception_available() -> bool:
    """True when the heavy deps (onnxruntime + numpy) are importable."""
    try:
        import numpy  # noqa: F401
        import onnxruntime  # noqa: F401
    except ImportError:
        return False
    return True


def perceive_photo(data: bytes, mime: str) -> PerceptionResult | None:
    """Full local pass over one photo: object tags + faces (each with a
    persisted embedding and a match-or-unknown) + deterministic scene dict.

    Returns None — with a single warning log, not per call — when the
    perception deps aren't installed, so callers can wire this in
    unconditionally. Model weights download to the perception models dir on
    first use. Raises ValueError for bytes PIL can't decode as an image."""
    global _warned_deps_missing
    if not perception_available():
        if not _warned_deps_missing:
            logger.warning(
                "perception deps not installed — photos get no local tags/faces. "
                "Install with: pip install -r core/perception-requirements.txt"
            )
            _warned_deps_missing = True
        return None

    from PIL import Image, ImageOps, UnidentifiedImageError

    from .faces import detect_faces
    from .scene import analyze_scene
    from .yolo import detect_tags

    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError(f"not a decodable image ({mime})") from exc

    scene = analyze_scene(img)  # reads EXIF off the original, pre-transpose
    # Phone photos are usually stored rotated with an EXIF Orientation tag the
    # detectors never see — upright them before any model looks.
    img = ImageOps.exif_transpose(img)
    tags = detect_tags(img)

    # The photo itself is referenced by content hash, never stored again here —
    # the KB keeps the actual asset; this just lets an embedding say which
    # photo it came from.
    source = {"mime": mime, "sha256": hashlib.sha256(data).hexdigest()}
    faces: list[FaceObservation] = []
    for face in detect_faces(img):
        embedding_id = storage.save_embedding(face["vector"], source)
        best = storage.best_match(face["vector"])
        match = None
        if best is not None and best[1] >= FACE_MATCH_THRESHOLD:
            match = {"person_name": best[0], "score": round(float(best[1]), 4)}
        faces.append(FaceObservation(box=face["box"], embedding_id=embedding_id, match=match))

    return PerceptionResult(tags=tags, scene=scene, faces=faces)


def enroll_face(embedding_id: str, person_name: str) -> None:
    """Attach a stored embedding to a person (creates the lens profile if the
    name is new). The id comes from a FaceObservation persisted at observation
    time — no photo re-processing needed. Raises FileNotFoundError for an
    unknown id."""
    storage.enroll(embedding_id, person_name)


def lens_people() -> list[str]:
    """Names with at least one enrolled face embedding."""
    return storage.people()


__all__ = [
    "FACE_MATCH_THRESHOLD",
    "FaceObservation",
    "PerceptionResult",
    "enroll_face",
    "lens_people",
    "perceive_photo",
    "perception_available",
]
