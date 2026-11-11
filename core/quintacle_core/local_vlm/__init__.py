"""Local vision backend — a small VLM served by Ollama on localhost.

Lineage: NaviGatr (the owner's ENEE408 capstone) proved the local-first
vision pattern on Pi-class hardware — small quantized models on-device
(int8 TFLite on a Coral EdgeTPU), with anything too heavy offloaded over
HTTP (monocular depth ran on an EC2 GPU API). NaviGatr never ran a
language VLM — its "descriptions" were template sentences over detector
output — so the describer model here is new; the inherited part is the
split: try the small local model first, fall back to the network. See
docs/navigatr-vlm-notes.md for the archaeology.

Zero new dependencies: this talks to a localhost HTTP API with httpx
(already required via the Anthropic SDK). Everything is lazy — no env
read, no httpx import, no connection attempt until
describe_images_local() is actually called — so QUINTACLE_VISION=cloud
(the default) never pays any of this.

Two servers can sit behind that localhost URL, selected per call by
QUINTACLE_VISION_BACKEND:

  ollama (default)  Ollama's /api/chat (ollama.py) — the desktop daemon.
  off               no local VLM (2026-11-06) — returns None at once.
  llamacpp          llama.cpp's llama-server, OpenAI-compatible
                    /v1/chat/completions (llamacpp.py) — the only one of
                    the two that also runs on the phone (Termux /
                    llama.cpp-android; see phone/tier3-vlm/).

The selection lives here, inside the entry function, so the
QUINTACLE_VISION dispatch in nodes/kb/drop.py stays backend-agnostic.

[2026-11-11 correction: QUINTACLE_VISION=cloud is no longer the default —
local has been the default since 2026-11-06, and the dispatch is now
perception/image_policy.image_provider() (QUINTACLE_IMAGE_PROVIDER), where
QUINTACLE_VISION survives only as a deprecated alias (cloud maps to auto).]
"""

from __future__ import annotations

import io
import logging
import os

logger = logging.getLogger(__name__)

# 2026-11-07: real phone photos (12 MP+) blew qwen2.5vl:3b's default 4096
# context ("request (~4110 tokens) exceeds the available context size") —
# Qwen2.5-VL spends one token per 28x28 patch, so the image is downscaled
# here before ANY backend sees it, and the Ollama call raises num_ctx.
# 1024 px on the long side keeps labels/receipts legible (~1300 image
# tokens) while leaving room for the prompt and the answer.
MAX_SIDE_ENV = "QUINTACLE_VISION_MAX_SIDE"
DEFAULT_MAX_SIDE = 1024
JPEG_QUALITY = 85
# Routing/classification wants the same answer twice for the same photo:
# greedy decoding + a fixed seed (both backends honor these).
VLM_SEED = 42


def max_side() -> int:
    try:
        return max(64, int(os.environ.get(MAX_SIDE_ENV, "") or DEFAULT_MAX_SIDE))
    except ValueError:
        return DEFAULT_MAX_SIDE


def prepare_image(data: bytes, mime: str = "image/jpeg", *, limit: int | None = None) -> tuple[bytes, str]:
    """One photo made VLM-sized: EXIF orientation applied (a sideways phone
    shot reads upright — the pixels are rotated, the tag dropped), long side
    capped at `limit` (default QUINTACLE_VISION_MAX_SIDE / 1024), re-encoded
    as JPEG q85 (alpha flattened onto white). Bytes that Pillow can't open
    pass through untouched — the backend then fails/answers as before."""
    from PIL import Image, ImageOps

    limit = limit or max_side()
    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img)
        img.load()
    except Exception as exc:  # not an image Pillow knows — leave it to the backend
        logger.debug("local VLM: couldn't preprocess image (%s); sending as-is", exc)
        return data, mime
    if max(img.size) > limit:
        img.thumbnail((limit, limit), Image.Resampling.LANCZOS)
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        bg = Image.new("RGB", rgba.size, (255, 255, 255))
        bg.paste(rgba, mask=rgba.getchannel("A"))
        img = bg
    elif img.mode != "RGB":
        img = img.convert("RGB")
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=JPEG_QUALITY)
    return out.getvalue(), "image/jpeg"


def prepare_images(photos: list[tuple[bytes, str]]) -> list[tuple[bytes, str]]:
    return [prepare_image(data, mime) for data, mime in photos]


def describe_images_local(photos: list[tuple[bytes, str]], question: str | None = None) -> str | None:
    """Local-VLM entry point: route to the backend named by
    QUINTACLE_VISION_BACKEND (ollama | llamacpp, default ollama), keeping
    the shared contract — description text, or None when local vision is
    unavailable. Imports stay lazy so the unused backend costs nothing."""
    backend = os.environ.get("QUINTACLE_VISION_BACKEND", "ollama").strip().lower()
    if backend == "off":
        # 2026-11-06: an explicit "no local VLM here" (the test suite sets it
        # so a dev machine's Ollama is never hit; a phone without llama-server
        # can set it to skip the 2 s connect probe on every photo).
        return None
    if backend == "llamacpp":
        from .llamacpp import describe_images_llamacpp

        return describe_images_llamacpp(photos, question)

    from .ollama import describe_images_local as describe_images_ollama

    return describe_images_ollama(photos, question)


__all__ = ["DEFAULT_MAX_SIDE", "VLM_SEED", "describe_images_local", "prepare_image", "prepare_images"]
