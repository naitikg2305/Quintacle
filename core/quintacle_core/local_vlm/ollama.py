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

_NUM_CTX = 8192


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
    from . import VLM_SEED, prepare_images

    photos = prepare_images(photos)  # 2026-11-07: downscale + EXIF-orient (context overflow fix)
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
    # 2026-11-07: Ollama's 4096 default overflowed on real phone photos;
    # 8192 fits a ~1024 px image + prompt + answer. temperature 0 + a fixed
    # seed: these answers drive routing, so they must repeat.
    options: dict = {"num_ctx": _NUM_CTX, "temperature": 0, "seed": VLM_SEED}
    pinned = _pinned_num_gpu(base_url, model)
    if pinned is not None:
        options["num_gpu"] = pinned
    payload["options"] = options

    status, text, detail = _post(httpx, base_url, payload, model)
    if status is None:
        return None
    if pinned is None and _looks_garbled(status, text, detail):
        # 2026-11-07: on the owner's RTX 5070 Ti (Ollama 0.34.2) a fully
        # GPU-offloaded qwen2.5vl answers every IMAGE prompt with "????…"
        # (or aborts: "token repeat limit reached"); text prompts are fine,
        # and keeping the output layer off the GPU (num_gpu = block_count)
        # fixes it at full speed (~1 s warm). Retry once that way and
        # remember it for this daemon+model; QUINTACLE_VISION_NUM_GPU pins it.
        layers = _block_count(httpx, base_url, model)
        logger.warning(
            "local VLM (%s) returned garbled output with full GPU offload — retrying with num_gpu=%s", model, layers
        )
        payload = {**payload, "options": {**options, "num_gpu": layers}}
        status, text, detail = _post(httpx, base_url, payload, model)
        if status is None:
            return None
        if not _looks_garbled(status, text, detail):
            _GPU_FALLBACK[(base_url, model)] = layers

    if status != 200:
        # A 404 here is almost always "model not pulled".
        logger.warning(
            "local VLM request failed (%s %s): %s — if the model is missing, run `ollama pull %s`",
            status,
            base_url,
            detail,
            model,
        )
        return None
    if _is_garbage(text):
        logger.warning("local VLM (%s) returned garbled output (%r…) — treating as unavailable", model, text[:20])
        return None
    return text or None


# (base_url, model) -> num_gpu that produced sane output after a garbled one.
_GPU_FALLBACK: dict[tuple[str, str], int] = {}


def _pinned_num_gpu(base_url: str, model: str) -> int | None:
    raw = os.environ.get("QUINTACLE_VISION_NUM_GPU", "").strip()
    if raw:
        try:
            return int(raw)
        except ValueError:
            logger.warning("QUINTACLE_VISION_NUM_GPU=%r is not an integer — ignored", raw)
    return _GPU_FALLBACK.get((base_url, model))


def _post(httpx, base_url: str, payload: dict, model: str) -> tuple[int | None, str, str]:
    """(status, answer text, error detail); status None = daemon unreachable."""
    try:
        response = httpx.post(
            f"{base_url}/api/chat",
            json=payload,
            timeout=httpx.Timeout(_READ_TIMEOUT, connect=_CONNECT_TIMEOUT),
        )
    except Exception as exc:  # connection refused, timeout, DNS — all mean "no local vision right now"
        logger.warning("local VLM unavailable (%s at %s): %s", model, base_url, exc)
        return None, "", ""
    if response.status_code != 200:
        try:
            detail = response.json().get("error", "")
        except Exception:
            detail = response.text[:200]
        return response.status_code, "", str(detail)
    try:
        text = (response.json().get("message") or {}).get("content", "")
    except Exception as exc:
        logger.warning("local VLM returned unparseable response: %s", exc)
        return None, "", ""
    return 200, (text or "").strip(), ""


def _is_garbage(text: str) -> bool:
    """An answer made only of '?' / replacement chars / whitespace."""
    return bool(text) and not text.strip("?\ufffd \n\t")


def _looks_garbled(status: int, text: str, detail: str) -> bool:
    return (status == 200 and _is_garbage(text)) or (status != 200 and "repeat limit" in detail.lower())


def _block_count(httpx, base_url: str, model: str) -> int:
    """The model's transformer block count from /api/show (qwen2.5vl:3b = 36);
    0 (CPU only — slow but always sane) when it can't be read."""
    try:
        r = httpx.post(f"{base_url}/api/show", json={"model": model}, timeout=httpx.Timeout(10.0, connect=_CONNECT_TIMEOUT))
        info = r.json().get("model_info") or {}
        for key, value in info.items():
            if key.endswith(".block_count") and isinstance(value, int) and value > 0:
                return value
    except Exception as exc:
        logger.debug("local VLM: /api/show failed (%s)", exc)
    return 0
