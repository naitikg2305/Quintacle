from __future__ import annotations

import base64
import logging
import os

logger = logging.getLogger(__name__)

_DEFAULT_URL = "http://localhost:11434"

# qwen2.5vl:3b (~3.2GB, Qwen2.5-VL 3B) over moondream (~1.7GB): moondream is
# faster but terse and misses text-in-image; Qwen2.5-VL at 3B reads labels,
# receipts and scene detail well enough to stand in for the cloud caption in
# a knowledge base. Both fit this machine; swap via QUINTACLE_VISION_MODEL.
_DEFAULT_MODEL = "qwen2.5vl:3b"

# Connect fast-fails so QUINTACLE_VISION=auto with no daemon costs ~2s, not a
# hang; the read timeout is generous because the first call after idle
# cold-loads several GB of weights before a single token comes back.
_CONNECT_TIMEOUT = 2.0
_READ_TIMEOUT = 300.0


def describe_images_local(photos: list[tuple[bytes, str]], question: str | None = None) -> str | None:
    """Mirror of describe_images (nodes/kb/drop.py) against a local VLM.

    Returns the description text, or None whenever local vision is not
    available — daemon down, model not pulled, request failed, empty
    answer. Callers (the QUINTACLE_VISION dispatch) decide whether None
    means "fall back to cloud" (auto) or "error out" (local)."""
    import httpx  # lazy: the cloud-only path never imports or configures this

    base_url = os.environ.get("QUINTACLE_OLLAMA_URL", _DEFAULT_URL).rstrip("/")
    model = os.environ.get("QUINTACLE_VISION_MODEL", _DEFAULT_MODEL)

    from ..nodes.vision import vision_prompt

    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": vision_prompt(len(photos), question),
                # Ollama takes raw base64 image payloads; mime is implied.
                "images": [base64.standard_b64encode(data).decode() for data, _mime in photos],
            }
        ],
        "stream": False,
    }

    try:
        response = httpx.post(
            f"{base_url}/api/chat",
            json=payload,
            timeout=httpx.Timeout(_READ_TIMEOUT, connect=_CONNECT_TIMEOUT),
        )
    except Exception as exc:  # connection refused, timeout, DNS — all mean "no local vision right now"
        logger.warning("local VLM unavailable (%s at %s): %s", model, base_url, exc)
        return None

    if response.status_code != 200:
        # A 404 here is almost always "model not pulled".
        try:
            detail = response.json().get("error", "")
        except Exception:
            detail = response.text[:200]
        logger.warning(
            "local VLM request failed (%s %s): %s — if the model is missing, run `ollama pull %s`",
            response.status_code,
            base_url,
            detail,
            model,
        )
        return None

    try:
        text = (response.json().get("message") or {}).get("content", "")
    except Exception as exc:
        logger.warning("local VLM returned unparseable response: %s", exc)
        return None

    text = text.strip()
    return text or None
