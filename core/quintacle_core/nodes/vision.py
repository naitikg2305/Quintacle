from __future__ import annotations

import base64


def image_content_blocks(photos: list[tuple[bytes, str]]) -> list[dict]:
    """One or two (data, mime_type) photos as Claude vision content blocks —
    e.g. the front of a product and its nutrition label, or the front/back
    of an ID, meant to be read together as views of the SAME thing, not two
    separate items. Shared by every vision-extraction call in the app so a
    second photo Just Works everywhere instead of being wired per-domain."""
    return [
        {"type": "image", "source": {"type": "base64", "media_type": mime, "data": base64.standard_b64encode(data).decode()}}
        for data, mime in photos
    ]


def vision_prompt(n_photos: int, question: str | None = None) -> str:
    """The one photo-description prompt every vision backend uses — the cloud
    path (describe_images) and the local path (describe_images_local) share
    it, so flipping QUINTACLE_VISION changes WHO answers, never what is
    being asked."""
    if question and question.strip():
        return (
            f"Answer this question about the attached photo{'s' if n_photos > 1 else ''}, "
            f"based only on what's actually visible: {question.strip()}"
        )
    if n_photos > 1:
        return (
            "These are two photos of the same thing (e.g. front and back, or a closer detail shot) "
            "— describe them together in a few sentences, for filing into a personal knowledge base."
        )
    return "Describe what's in this image in a few sentences, for filing into a personal knowledge base."
