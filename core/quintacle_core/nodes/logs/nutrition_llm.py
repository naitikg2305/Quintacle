from __future__ import annotations

import anthropic
from pydantic import BaseModel

from ...llm_config import DEFAULT_MODEL
from ...llm_dispatch import parse_structured
from ..vision import image_content_blocks
from .nutrition_targets import NUTRIENT_UNITS
from ...max_backend import cloud_client

_SYSTEM_PROMPT = (
    "Estimate full nutrition for a described food. Give macros (protein, carbs, fat, fiber, "
    "kcal in grams/kcal) and an amount for every one of these micronutrients, each in the "
    "exact unit specified — do not substitute a different unit (e.g. copper must be in mcg, "
    "not mg):\n"
    + "\n".join(f"- {nutrient}: {unit}" for nutrient, unit in NUTRIENT_UNITS.items())
    + "\n\nUse realistic food-composition knowledge. Include every micronutrient listed, "
    "even if the amount is 0 — don't skip any. Also state basis_amount_g: the weight in "
    "grams that your numbers above correspond to (the amount mentioned in the text, or 100 "
    "if none was given) — this is an ingredient preset, reusable at any quantity later by "
    "scaling against this basis."
)

_IMAGE_SYSTEM_PROMPT = (
    _SYSTEM_PROMPT
    + "\n\nYou're reading this from one or two photos of the SAME product/food (e.g. the front "
    "of a package plus its nutrition facts label, or a dish from two angles) — either a "
    "nutrition facts label (read the stated values directly; basis_amount_g is the label's "
    "serving size in grams, or 100 if it states per-100g) or a raw/prepared food item (estimate "
    "from what's visibly in the photo(s), plus any text given alongside it; basis_amount_g is "
    "your best estimate of the pictured quantity's weight in grams — when a label photo is "
    "present, prefer its printed values over a visual estimate). Also propose a short "
    "suggested_name for this ingredient (e.g. the product name on a label, or a plain "
    "description of the food). Set from_label to true only if you read the numbers from a printed "
    "nutrition facts label. ingredients: copy the label's INGREDIENTS line exactly as printed if one is "
    "visible, else leave it empty."
)


class MicroEstimate(BaseModel):
    nutrient: str
    amount: float
    unit: str


class NutritionEstimate(BaseModel):
    basis_amount_g: float
    protein_g: float
    carbs_g: float
    fat_g: float
    fiber_g: float
    kcal: float
    micros: list[MicroEstimate]


class NutritionEstimateFromImage(NutritionEstimate):
    suggested_name: str
    # 2026-11-05: True when the numbers were READ off a printed nutrition
    # label (they win, source=label); False for a visual estimate of a plain
    # food — then USDA numbers replace them when the food matches.
    from_label: bool = False
    # 2026-11-18 (owner): the printed INGREDIENTS line ("LAMB"); picks the USDA food for the backfill.
    ingredients: str = ""


def estimate_nutrition(description: str, provider: str | None = None) -> NutritionEstimate:
    return parse_structured(_SYSTEM_PROMPT, description, NutritionEstimate, provider=provider, max_tokens=4096).parsed


class LocalNutritionReading(NutritionEstimateFromImage):
    """What the LOCAL photo lane returns (2026-11-06) — the cloud schema plus
    read-metadata the review card can show. Never sent to a model as a
    schema (the cloud call still uses NutritionEstimateFromImage)."""

    field_confidence: dict[str, float] = {}
    label_dv: dict[str, float] = {}
    serving_size_text: str = ""
    servings_per_container: float | None = None
    per_100g: bool = False
    # 2026-11-06: the OCR text rides along (never to a model) so the USDA
    # fill can backtrack the food from the label's numbers + ingredient words.
    ocr_text: str = ""


_LABEL_TEXT_PROMPT = (
    "You are given OCR text read from a photographed nutrition facts label (it may contain OCR "
    "errors, e.g. O for 0, l for 1, values split across lines). Read the values the LABEL STATES — "
    "never estimate from food knowledge. Give macros (protein_g, carbs_g, fat_g, fiber_g in grams, "
    "kcal) per serving, basis_amount_g = the serving size in grams (100 if the panel is per 100 g), "
    "and micros ONLY for nutrients printed on the label, each in exactly this unit:\n"
    + "\n".join(f"- {nutrient}: {unit}" for nutrient, unit in NUTRIENT_UNITS.items())
    + "\nIf a row shows only a %DV, leave it out (code converts those). suggested_name: the product "
    "name if the text shows one, else a short plain description. from_label: true."
)

_FOOD_QUESTION = (
    "What food is in this photo? Reply in exactly this format:\n"
    "NAME: <short plain food name, e.g. grilled chicken breast>\n"
    "GRAMS: <your best estimate of the pictured amount's weight in grams, a number>"
)


def parse_food_answer(answer: str) -> tuple[str, float | None]:
    """The local VLM's 'NAME: x / GRAMS: n' reply -> (name, grams|None), in
    code; tolerant of a bare sentence reply."""
    import re

    from ...perception.local_describe import first_sentence, parse_kv

    kv = parse_kv(answer, ("name", "grams", "weight"))
    name = (kv.get("name") or first_sentence(answer, 60)).strip(" .\"'")
    grams_field = kv.get("grams") or kv.get("weight")
    m = re.search(r"(\d+(?:\.\d+)?)", grams_field) if grams_field else re.search(r"(\d+(?:\.\d+)?)\s*(?:g|grams?)\b", answer)
    grams = float(m.group(1)) if m else None
    if grams is not None and not (1 <= grams <= 5000):
        grams = None
    return name[:60], grams


def _estimate_from_image_local(photos: list[tuple[bytes, str]], user_description: str) -> tuple[LocalNutritionReading, str]:
    """OCR -> deterministic label parse (done, no model, when calories +
    protein + carbs + fat are all read) -> local TEXT model over the OCR
    text for the rest. No label text -> YOLO tags + local VLM name the food
    and its weight; the numbers then come from USDA (the caller's
    _source_ingredient_image), or the local text model's estimate when
    USDA has no match."""
    from ...perception.image_policy import LocalImageUnavailable
    from ...perception.image_router import FOOD_TAGS, classify_text, detect_photo_tags
    from ...perception.ocr import ocr_image
    from .label_parser import guess_product_name, overlay_parsed, parse_label, to_estimate

    readings = [r for r in (ocr_image(data) for data, _mime in photos) if r is not None and r.text.strip()]
    ocr_text = "\n".join(r.text for r in readings)
    user_name = user_description.strip().splitlines()[0][:60] if user_description.strip() else ""
    if ocr_text:
        parse = parse_label(ocr_text, [ln.conf for r in readings for ln in r.lines])
        labelish = classify_text(ocr_text) == "nutrition_label" or sum(parse.has(k) for k in ("kcal", "protein_g", "carbs_g", "fat_g")) >= 2
        if labelish:
            # 2026-11-07: the name comes from the owner's text or the OCR
            # heuristic over the individual (deskewed) fragments — never the
            # model. Nothing name-like → "Labeled food"; the USDA profile
            # match (api._source_ingredient_image) then names it.
            name = user_name
            for r in readings:
                name = name or guess_product_name(r.fragments or r.lines)
            name = name or "Labeled food"
            if parse.core_complete:
                return LocalNutritionReading(**to_estimate(parse, name), ocr_text=ocr_text[:4000]), "ocr+parser"
            content = f"OCR text of the label:\n{ocr_text}" + (f"\n\nThe owner adds: {user_description.strip()}" if user_description.strip() else "")
            model = parse_structured(_LABEL_TEXT_PROMPT, content, NutritionEstimateFromImage, provider="local", max_tokens=2048).parsed
            fields = overlay_parsed(model.model_dump(), parse, name)
            return LocalNutritionReading(**fields, ocr_text=ocr_text[:4000]), "ocr+local-llm"

    # A plain food photo: name + weight from the local VLM (YOLO tags as a hint / fallback).
    from ...local_vlm import describe_images_local

    tags = detect_photo_tags(photos[0][0]) or []
    hint = f"\nAn object detector saw: {', '.join(tags[:6])}." if tags else ""
    if user_description.strip():
        hint += f"\nThe owner says: {user_description.strip()[:200]}"
    answer = describe_images_local(photos, _FOOD_QUESTION + hint)
    if answer:
        name, grams = parse_food_answer(answer)
        pipeline = "yolo+local-vlm"
    else:
        food = [t for t in tags if t in FOOD_TAGS]
        if not food and not user_name:
            raise LocalImageUnavailable(
                "no nutrition-label text found and no local vision model to recognize the food "
                "(install OCR / start Ollama with qwen2.5vl:3b)",
                what="food photo",
            )
        name, grams, pipeline = (food[0] if food else user_name), None, "yolo"
    name = user_name or name
    basis = grams or 100.0
    from .usda_sourcing import usda_proposal

    usda = usda_proposal(name, basis) or {}
    if usda.get("matched"):  # numbers come from USDA downstream — no model estimate needed
        fields = {"protein_g": 0.0, "carbs_g": 0.0, "fat_g": 0.0, "fiber_g": 0.0, "kcal": 0.0, "micros": []}
    else:
        description = f"{name}, about {basis:g} g" + (f". {answer}" if answer else "")
        fields = estimate_nutrition(description, provider="local").model_dump()
        fields.pop("basis_amount_g", None)
    return LocalNutritionReading(**fields, basis_amount_g=basis, suggested_name=name, from_label=False), pipeline


def estimate_nutrition_from_image(
    photos: list[tuple[bytes, str]], user_description: str = "", provider: str | None = None
) -> NutritionEstimateFromImage:
    """Vision-based counterpart to estimate_nutrition() — for one or two
    photographed nutrition labels/prepared meals (e.g. front of package +
    its label), not typed text. Feeds the same preset-creation flow
    (POST /logs/meals) once reviewed.

    2026-11-06: local-first per perception/image_policy.py — OCR + the
    deterministic label parser first; the cloud vision call below runs only
    on provider=cloud (Redo with cloud) or the auto fallback."""
    from ...perception.image_policy import run_image_task

    return run_image_task(
        lambda: _estimate_from_image_local(photos, user_description),
        lambda: _estimate_from_image_cloud(photos, user_description),
        what="nutrition photo",
        provider=provider,
    )


def _estimate_from_image_cloud(photos: list[tuple[bytes, str]], user_description: str = "") -> NutritionEstimateFromImage:
    client = cloud_client()
    content: list[dict] = image_content_blocks(photos)
    if user_description.strip():
        content.append({"type": "text", "text": user_description.strip()})
    response = client.messages.parse(
        model=DEFAULT_MODEL,
        max_tokens=4096,
        system=_IMAGE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": content}],
        output_format=NutritionEstimateFromImage,
    )
    return response.parsed_output
