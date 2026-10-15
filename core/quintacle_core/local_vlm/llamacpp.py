from __future__ import annotations

import base64
import logging
import os

logger = logging.getLogger(__name__)

# llama-server's default bind. Unlike Ollama there is no daemon-wide model
# registry — the server hosts whatever GGUF (+ --mmproj) it was launched
# with, so the URL is the whole address of "which model".
_DEFAULT_URL = "http://127.0.0.1:8080"

# llama-server ignores the OpenAI `model` field for routing (one server, one
# model); we still send QUINTACLE_VISION_MODEL when set so logs and clients
# that read it back stay truthful.
_CONNECT_TIMEOUT = 2.0
_READ_TIMEOUT = 300.0


def describe_images_llamacpp(photos: list[tuple[bytes, str]], question: str | None = None) -> str | None:
    """Mirror of describe_images_local (ollama.py) against llama.cpp's
    llama-server — the backend that also runs on the phone (Termux /
    llama.cpp-android), where Ollama does not exist. See phone/tier3-vlm/.

    Speaks llama-server's OpenAI-compatible /v1/chat/completions with
    base64 data-URL image parts (how llama.cpp multimodal serves; needs the
    model's mmproj loaded via --mmproj). Returns the description text, or
    None whenever local vision is not available — server down, request
    failed, empty answer — so the QUINTACLE_VISION dispatch can fall back
    (auto) or error out (local) exactly as with the Ollama backend."""
    import httpx  # lazy: the cloud-only path never imports or configures this

    base_url = os.environ.get("QUINTACLE_LLAMACPP_URL", _DEFAULT_URL).rstrip("/")
    model = os.environ.get("QUINTACLE_VISION_MODEL")

    from ..nodes.vision import vision_prompt

    content: list[dict] = [
        # OpenAI-style content parts: images as data URLs, mime kept honest.
        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{base64.standard_b64encode(data).decode()}"}}
        for data, mime in photos
    ]
    content.append({"type": "text", "text": vision_prompt(len(photos), question)})

    payload: dict = {
        "messages": [{"role": "user", "content": content}],
        "stream": False,
    }
    if model:
        payload["model"] = model

    try:
        response = httpx.post(
            f"{base_url}/v1/chat/completions",
            json=payload,
            timeout=httpx.Timeout(_READ_TIMEOUT, connect=_CONNECT_TIMEOUT),
        )
    except Exception as exc:  # connection refused, timeout, DNS — all mean "no local vision right now"
        logger.warning("local VLM unavailable (llama-server at %s): %s", base_url, exc)
        return None

    if response.status_code != 200:
        # A 500 mentioning "image input" usually means the server was
        # started without --mmproj; 400s mean a model with no vision at all.
        try:
            detail = (response.json().get("error") or {}).get("message", "")
        except Exception:
            detail = response.text[:200]
        logger.warning(
            "local VLM request failed (%s %s): %s — is llama-server running with a multimodal GGUF and --mmproj?",
            response.status_code,
            base_url,
            detail,
        )
        return None

    try:
        choices = response.json().get("choices") or []
        text = ((choices[0].get("message") or {}).get("content") or "") if choices else ""
    except Exception as exc:
        logger.warning("local VLM returned unparseable response: %s", exc)
        return None

    text = text.strip()
    return text or None
