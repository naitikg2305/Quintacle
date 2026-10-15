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
  llamacpp          llama.cpp's llama-server, OpenAI-compatible
                    /v1/chat/completions (llamacpp.py) — the only one of
                    the two that also runs on the phone (Termux /
                    llama.cpp-android; see phone/tier3-vlm/).

The selection lives here, inside the entry function, so the
QUINTACLE_VISION dispatch in nodes/kb/drop.py stays backend-agnostic.
"""

from __future__ import annotations

import os


def describe_images_local(photos: list[tuple[bytes, str]], question: str | None = None) -> str | None:
    """Local-VLM entry point: route to the backend named by
    QUINTACLE_VISION_BACKEND (ollama | llamacpp, default ollama), keeping
    the shared contract — description text, or None when local vision is
    unavailable. Imports stay lazy so the unused backend costs nothing."""
    backend = os.environ.get("QUINTACLE_VISION_BACKEND", "ollama").strip().lower()
    if backend == "llamacpp":
        from .llamacpp import describe_images_llamacpp

        return describe_images_llamacpp(photos, question)

    from .ollama import describe_images_local as describe_images_ollama

    return describe_images_ollama(photos, question)


__all__ = ["describe_images_local"]
