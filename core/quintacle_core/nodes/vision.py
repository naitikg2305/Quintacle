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
