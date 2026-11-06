"""Local stand-ins for the cloud describe_* estimators (2026-11-06).

The wardrobe / grooming / outfit-photo / food-photo extractors used to send
the image to a cloud model with a Pydantic schema. Locally there is no
vision+schema model, so the split is: the local VLM (qwen2.5vl:3b) answers a
FORMATTED question ("NAME: ... / CATEGORY: ... / DESCRIPTION: ..."), and
code parses that reply into the schema — category snapped onto the known
vocabulary in code, never trusted free-form. When the VLM isn't available,
OCR text (a product label) and YOLO tags still give a usable proposal,
flagged by the pipeline name.
"""

from __future__ import annotations

import re

from .image_policy import LocalImageUnavailable


def parse_kv(answer: str, keys: tuple[str, ...]) -> dict[str, str]:
    """'NAME: x\\nCATEGORY: y' -> {'name': 'x', 'category': 'y'}; tolerant of
    markdown bold, bullets, and a key's value running onto following lines."""
    out: dict[str, str] = {}
    current = None
    for raw in (answer or "").splitlines():
        line = raw.strip().lstrip("-*• ").replace("**", "")
        m = re.match(rf"(?i)^({'|'.join(re.escape(k) for k in keys)})\s*[:=\-]\s*(.*)$", line)
        if m:
            current = m.group(1).lower()
            out[current] = m.group(2).strip()
        elif current and line:
            out[current] = (out[current] + " " + line).strip()
    return out


def snap_category(value: str, allowed: tuple[str, ...], text: str = "") -> str:
    """A model's category word snapped onto the known vocabulary; falls
    back to scanning the description; else the value lowercased (the
    estimators allow "another short lowercase category")."""
    low = (value or "").strip().lower()
    for cat in allowed:
        if low == cat or low.rstrip("s") == cat or cat in low.split():
            return cat
    for cat in allowed:
        if re.search(rf"\b{re.escape(cat)}s?\b", (text or "").lower()):
            return cat
    word = re.sub(r"[^a-z ]", "", low).strip()
    return word.split()[0] if word else (allowed[-1] if allowed else "")


def first_sentence(text: str, limit: int = 160) -> str:
    s = re.split(r"(?<=[.!?])\s", (text or "").strip(), maxsplit=1)[0]
    return s[:limit]


def ask_vlm(photos: list[tuple[bytes, str]], question: str) -> str | None:
    from ..local_vlm import describe_images_local

    return describe_images_local(photos, question)


def describe_item_local(
    photos: list[tuple[bytes, str]],
    *,
    noun: str,
    categories: tuple[str, ...],
    user_description: str = "",
    tag_categories: dict[str, str] | None = None,
    category_keywords: dict[str, str] | None = None,
    use_ocr: bool = False,
) -> tuple[dict, str]:
    """{suggested_name, category, description} for one item photographed in
    one or two views, plus the pipeline that produced it. Order: local VLM
    (with OCR text / YOLO tags as hints) -> OCR label text -> YOLO tag.
    Raises LocalImageUnavailable when none of them yields anything."""
    from .image_router import detect_photo_tags
    from .ocr import ocr_image

    data = photos[0][0]
    tags = detect_photo_tags(data) or []
    ocr_text = ""
    ocr_lines = []
    if use_ocr:
        for photo, _mime in photos:
            r = ocr_image(photo)
            if r is not None and r.text.strip():
                ocr_text += ("\n" if ocr_text else "") + r.text
                ocr_lines += r.lines
    hints = ""
    if ocr_text:
        hints += f"\nText printed on it (OCR): {ocr_text[:600]}"
    if tags:
        hints += f"\nAn object detector saw: {', '.join(tags[:6])}."
    if user_description.strip():
        hints += f"\nThe owner says: {user_description.strip()[:300]}"
    question = (
        f"This is a photo of one {noun} (two photos = two views of the SAME {noun}). Reply in exactly this format:\n"
        f"NAME: <short name — brand + {noun} if visible, else a plain description>\n"
        f"CATEGORY: <one of: {', '.join(categories)}, or another short lowercase word>\n"
        "DESCRIPTION: <one sentence: color, material, notable details, what it's for>" + hints
    )
    answer = ask_vlm(photos, question)
    if answer:
        kv = parse_kv(answer, ("name", "category", "description"))
        description = kv.get("description") or first_sentence(answer)
        name = (kv.get("name") or first_sentence(answer, 60)).strip(" .\"'")
        category = snap_category(kv.get("category", ""), categories, f"{name} {description}")
        return {"suggested_name": name[:80], "category": category, "description": description}, "yolo+local-vlm"

    # No VLM: printed label text (a bottle, a tag) still names the product.
    if ocr_lines:
        from ..nodes.logs.label_parser import guess_product_name

        name = user_description.strip()[:80] or guess_product_name(ocr_lines) or first_sentence(ocr_text, 60)
        category = ""
        for kw, cat in (category_keywords or {}).items():
            if re.search(rf"(?i)\b{re.escape(kw)}", ocr_text + " " + user_description):
                category = cat
                break
        return {
            "suggested_name": name,
            "category": category or (categories[-1] if categories else ""),
            "description": f"Label text: {' '.join(ocr_text.split())[:200]}",
        }, "ocr+parser"
    for tag in tags:
        if tag_categories and tag in tag_categories:
            name = user_description.strip()[:80] or tag
            return {"suggested_name": name, "category": tag_categories[tag], "description": f"Detected locally: {tag}."}, "yolo"
    raise LocalImageUnavailable(
        f"no local vision model to describe this {noun} (start Ollama with qwen2.5vl:3b)", what=f"{noun} photo"
    )


__all__ = ["ask_vlm", "describe_item_local", "first_sentence", "parse_kv", "snap_category"]
