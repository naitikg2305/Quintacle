"""Perception's on-disk state — embeddings + enrolled-person profiles.

Everything lives under `<data dir>/perception/` (default `~/.quintacle/perception/`):

    perception/
      models/       downloaded ONNX weights (first-use download, never in the repo)
      embeddings/   one small JSON file per face observation:
                    {id, vector, source, created_at}
      profiles.json {"people": {"<name>": ["<embedding_id>", ...]}}

BIOMETRIC PRIVACY RULE: embedding vectors never leave this directory. They are
never written into KB markdown, never sent to any API/LLM, never put on graph
edges — edges and journal entries carry person NAMES only. The directory syncs
as opaque bytes via the existing LAN sync like everything else under the data
dir, which is fine: it stays device-to-device.

Deliberately stdlib-only (json + pure-python cosine): enrollment and the
people lens keep working even in an install without the heavy perception
deps (onnxruntime/numpy), and the matching math is testable dep-free.
"""

from __future__ import annotations

import json
import math
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

_lock = threading.Lock()


def perception_root() -> Path:
    """Resolved per call (not at import) so tests pointing QUINTACLE_DATA_DIR
    at a tmp dir get isolated perception state too."""
    data_dir = Path(os.environ.get("QUINTACLE_DATA_DIR", Path.home() / ".quintacle"))
    return data_dir / "perception"


def embeddings_dir() -> Path:
    return perception_root() / "embeddings"


def profiles_path() -> Path:
    return perception_root() / "profiles.json"


def models_dir() -> Path:
    """Where ONNX weights live. Overridable via QUINTACLE_PERCEPTION_MODELS_DIR
    so tests with a tmp QUINTACLE_DATA_DIR can still reuse one downloaded copy
    instead of re-fetching ~19 MB per test dir."""
    override = os.environ.get("QUINTACLE_PERCEPTION_MODELS_DIR")
    return Path(override) if override else perception_root() / "models"


def save_embedding(vector: list[float], source: dict) -> str:
    """Persist one face observation's vector at observation time and return its
    id — the handle the tag-confirm flow later enrolls by, without ever
    re-processing the photo. `source` is a reference to the photo (mime +
    content sha256), not the photo itself."""
    embedding_id = uuid.uuid4().hex
    directory = embeddings_dir()
    directory.mkdir(parents=True, exist_ok=True)
    payload = {
        "id": embedding_id,
        "vector": [float(v) for v in vector],
        "source": source,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    (directory / f"{embedding_id}.json").write_text(json.dumps(payload))
    return embedding_id


def load_embedding(embedding_id: str) -> dict | None:
    # Clamp to a bare hex-ish name — ids come back over HTTP/MCP, so never
    # let one smuggle a path into the data dir.
    if not embedding_id.replace("-", "").isalnum():
        return None
    path = embeddings_dir() / f"{embedding_id}.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _load_profiles() -> dict[str, list[str]]:
    path = profiles_path()
    if not path.is_file():
        return {}
    try:
        return dict(json.loads(path.read_text()).get("people", {}))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_profiles(people: dict[str, list[str]]) -> None:
    path = profiles_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"people": people}, indent=2, sort_keys=True))


def enroll(embedding_id: str, person_name: str) -> None:
    """Attach a stored embedding to a person, creating the lens profile if
    it's a new name. Raises FileNotFoundError for an id that was never
    persisted — enrollment must reference a real observation."""
    name = person_name.strip()
    if not name:
        raise ValueError("person_name must be non-empty")
    if load_embedding(embedding_id) is None:
        raise FileNotFoundError(f"no stored embedding with id {embedding_id!r}")
    with _lock:
        people = _load_profiles()
        ids = people.setdefault(name, [])
        if embedding_id not in ids:
            ids.append(embedding_id)
        _save_profiles(people)


def people() -> list[str]:
    return sorted(_load_profiles().keys())


def _cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return -1.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return -1.0
    return dot / (na * nb)


def best_match(vector: list[float]) -> tuple[str, float] | None:
    """Best enrolled person for a query vector: max cosine over every enrolled
    embedding (same best-of scheme as the PeopleLens prototype). Returns
    (name, score) or None when nobody is enrolled — the THRESHOLD decision
    (match vs unknown) belongs to the caller."""
    best: tuple[str, float] | None = None
    for name, ids in _load_profiles().items():
        for embedding_id in ids:
            stored = load_embedding(embedding_id)
            if stored is None:
                continue  # synced-away/deleted file — a stale id shouldn't break matching
            score = _cosine(vector, stored["vector"])
            if best is None or score > best[1]:
                best = (name, score)
    return best
