"""First-use download of the ONNX model weights into the perception models
dir (default `~/.quintacle/perception/models/`) — never into the repo, and
never at import time. These are the ONLY network fetches this package makes;
inference itself is fully local.

Models (all small, picked for onnxruntime-on-Python-3.14 and an eventual
phone port — no torch anywhere):

- yolox_nano.onnx (~3.5 MB) — object tags, 80 COCO classes. Official Megvii
  YOLOX release asset.
- det_500m.onnx (~2.5 MB) — SCRFD-500M face detector (boxes + 5 landmarks).
- w600k_mbf.onnx (~13 MB) — MobileFaceNet ArcFace recognizer, 512-d
  embeddings. Both from insightface's official `buffalo_sc` release zip.
"""

from __future__ import annotations

import logging
import shutil
import urllib.request
import zipfile
from pathlib import Path

from .storage import models_dir

logger = logging.getLogger(__name__)

YOLOX_NANO_URL = "https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_nano.onnx"
BUFFALO_SC_URL = "https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_sc.zip"

YOLO_MODEL = "yolox_nano.onnx"
FACE_DETECT_MODEL = "det_500m.onnx"
FACE_EMBED_MODEL = "w600k_mbf.onnx"


def _download(url: str, dest: Path) -> None:
    logger.info("perception: downloading model weights %s -> %s (first use only)", url, dest)
    tmp = dest.with_suffix(dest.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "Quintacle/1.0"})
    with urllib.request.urlopen(request, timeout=120) as response, open(tmp, "wb") as out:
        shutil.copyfileobj(response, out)
    tmp.replace(dest)
    logger.info("perception: downloaded %s (%.1f MB)", dest.name, dest.stat().st_size / 1e6)


def ensure_model(name: str) -> Path:
    """Return the local path of a model, downloading on first use."""
    directory = models_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    if path.is_file():
        return path
    if name == YOLO_MODEL:
        _download(YOLOX_NANO_URL, path)
        return path
    if name in (FACE_DETECT_MODEL, FACE_EMBED_MODEL):
        # Both face models ship in one official zip — fetch once, extract the
        # .onnx members flat into models/ (the zip nests them under buffalo_sc/).
        zip_path = directory / "buffalo_sc.zip"
        if not zip_path.is_file():
            _download(BUFFALO_SC_URL, zip_path)
        with zipfile.ZipFile(zip_path) as archive:
            for member in archive.namelist():
                base = Path(member).name
                if member.endswith(".onnx") and not (directory / base).is_file():
                    with archive.open(member) as src, open(directory / base, "wb") as out:
                        shutil.copyfileobj(src, out)
                    logger.info("perception: extracted %s from %s", base, zip_path.name)
        if not path.is_file():
            raise FileNotFoundError(f"{name} not found inside {zip_path}")
        return path
    raise ValueError(f"unknown perception model: {name}")
