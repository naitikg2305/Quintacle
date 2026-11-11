"""Chat nutrition lane (2026-11-05) — "say I discuss a lamb meal, will it
track everything inside the lamb?"

Same shape as the web lane (web_search.chat_web_block): one function that
returns an optional context block, called next to it in kb/chat.py. When the
newest user message is about food/nutrition, CODE parses the food items +
quantities, matches each against the offline USDA db, scales the per-100 g
values and hands the model a finished facts block — every tracked nutrient
incl. fatty acids/flavonoids/carotenoids, % of the owner's targets, and the
USDA description that was assumed. The model is told to use these numbers
and not estimate others. No db installed → no block (never the network).
No note content is involved — only the user's own message.
"""
from __future__ import annotations

import logging
import os
import re

from . import store as usda
from .nutrients import NUTRIENTS
from .panel import build_panel

logger = logging.getLogger(__name__)

_NUTRIENT_WORDS = sorted(
    {w for n in NUTRIENTS for w in re.findall(r"[a-z][a-z\-]{3,}", n.name.lower())}
    - {"total", "acid", "omega", "fat"},
    key=len, reverse=True,
)
_CUES = re.compile(
    r"\b(nutrients?|nutrition(al)?|macros?|micros?|calories|kcal|protein|carbs?|vitamins?|minerals?|omega[- ]?[36]s?|"
    r"flavonoids?|flavanols?|carotenoids?|fatty acids?|how much .{1,40}\b(in|does)\b|" + "|".join(map(re.escape, _NUTRIENT_WORDS)) + r")\b",
    re.I,
)
_UNIT_G = {"g": 1, "gram": 1, "grams": 1, "kg": 1000, "kgs": 1000, "oz": 28.3495, "ounce": 28.3495, "ounces": 28.3495,
           "lb": 453.592, "lbs": 453.592, "pound": 453.592, "pounds": 453.592}
# Typical single-item weights (USDA FNDDS "1 medium" portions) for counted foods.
_EACH_G = {"egg": 50, "eggs": 50, "banana": 118, "bananas": 118, "apple": 182, "apples": 182, "orange": 131,
           "oranges": 131, "avocado": 150, "avocados": 150, "tortilla": 45, "tortillas": 45, "slice": 28, "slices": 28}
_QTY_FOOD = re.compile(
    r"\b(\d+(?:\.\d+)?)\s*(kg|kgs|g|grams?|oz|ounces?|lbs?|pounds?)\b\s*(?:of\s+)?([a-z][a-z \-']{1,40})",
    re.I,
)
_COUNT_FOOD = re.compile(r"\b(\d+)\s+(?:(?:large|medium|small)\s+)?(" + "|".join(_EACH_G) + r")\b([a-z \-']{0,30})", re.I)
_SPLIT = re.compile(r"\s*(?:,|;|\band\b|\bwith\b|\bplus\b|&|\+)\s*", re.I)
_TAIL_STOP = re.compile(r"\b(for|today|tonight|yesterday|this|that|which|how|what|is|are|was|would|will|i|to|at)\b.*$", re.I)
_LEAD_JUNK = re.compile(r"^(?:a|an|the|my|some|of|about|roughly|around)\s+", re.I)


# 2026-11-11: which nutrient(s) the question is about, so the block answers
# THAT nutrient first and says which USDA entry its number came from.
_GROUP_WORDS = {
    r"omega[- ]?3s?": ("ALA (omega-3)", "EPA (omega-3)", "DPA (omega-3)", "DHA (omega-3)"),
    r"omega[- ]?6s?": ("Linoleic acid (omega-6)",),
    r"flavonoids?": tuple(n.name for n in NUTRIENTS if n.group == "Flavonoids"),
    r"carotenoids?": tuple(n.name for n in NUTRIENTS if n.group == "Carotenoids"),
    r"calories|kcal|energy": ("Energy",),
    r"carbs?|carbohydrates?": ("Carbohydrates",),
    r"sugars?": ("Total Sugars",),
    r"saturated fats?": ("Saturated Fat",),
    r"b1": ("Thiamin (B1)",), r"b2": ("Riboflavin (B2)",), r"b3": ("Niacin (B3)",), r"b5": ("Pantothenic Acid (B5)",),
}
# Total-fat etc. are only asked for when the bare word isn't part of a longer name.
_BARE = {"Fat": r"(?<!saturated )(?<!unsaturated )(?<!trans )\bfat\b", "Protein": r"\bprotein\b", "Fiber": r"\bfib(?:er|re)\b"}


def _nutrient_patterns() -> list[tuple[re.Pattern, tuple[str, ...]]]:
    pats = [(re.compile(rf"\b(?:{k})\b", re.I), v) for k, v in _GROUP_WORDS.items()]
    pats += [(re.compile(v, re.I), (k,)) for k, v in _BARE.items()]
    for n in NUTRIENTS:
        if n.name in _BARE or n.name in ("Energy", "Carbohydrates", "Total Sugars", "Saturated Fat"):
            continue
        base = re.sub(r"\s*\(.*\)", "", n.name).strip().lower()
        alts = [re.escape(base)]
        if base.startswith("vitamin "):
            alts.append(r"vit\.?\s*" + re.escape(base.split(" ", 1)[1]))
        pats.append((re.compile(rf"\b(?:{'|'.join(alts)})\b", re.I), (n.name,)))
    return pats


_NUTRIENT_PATS = _nutrient_patterns()


def asked_nutrients(text: str) -> list[str]:
    """Nutrient names (NUTRIENTS spelling) the message asks about, in
    canonical order. Deterministic word match; empty = a general question."""
    hit = {name for pat, names in _NUTRIENT_PATS if pat.search(text or "") for name in names}
    return [n.name for n in NUTRIENTS if n.name in hit]


def is_food_message(text: str) -> bool:
    text = text or ""
    return bool(_CUES.search(text) or _QTY_FOOD.search(text) or _COUNT_FOOD.search(text))


def _clean(food: str) -> str:
    food = _TAIL_STOP.sub("", food.strip(" ?.!,'\"")).strip()
    while _LEAD_JUNK.match(food):
        food = _LEAD_JUNK.sub("", food)
    return food.strip(" -'")


def parse_items(text: str) -> list[dict]:
    """[{food, grams, assumed}] — deterministic. Quantity-first phrases
    ("200g roast lamb", "2 eggs"); otherwise the "in/of <food>" target of a
    nutrient question at 100 g (stated as assumed)."""
    items: list[dict] = []
    for part in _SPLIT.split(text or ""):
        m = _QTY_FOOD.search(part)
        if m:
            food = _clean(m.group(3))
            if food:
                items.append({"food": food, "grams": round(float(m.group(1)) * _UNIT_G[m.group(2).lower()], 1), "assumed": False})
            continue
        c = _COUNT_FOOD.search(part)
        if c:
            noun = c.group(2).lower()
            food = _clean(f"{noun} {c.group(3)}") if noun in ("slice", "slices") else _clean(f"{c.group(3)} {noun}")
            items.append({"food": food or noun, "grams": int(c.group(1)) * _EACH_G[noun], "assumed": True,
                          "note": f"{c.group(1)} × ~{_EACH_G[noun]} g each"})
    if items:
        return items
    m = re.search(r"\b(?:in|of)\s+(.{2,80}?)(?:\?|$|\.)", text or "", re.I)
    if m:
        for part in _SPLIT.split(m.group(1)):
            food = _clean(part)
            if food and not _CUES.fullmatch(food):
                items.append({"food": food, "grams": 100.0, "assumed": True, "note": "no amount given — per 100 g"})
    return items


def _fmt(amount: float, unit: str) -> str:
    if amount == 0:
        return f"0 {unit}"
    if abs(amount) >= 100:
        return f"{amount:.0f} {unit}"
    if abs(amount) >= 1:
        return f"{amount:.1f} {unit}"
    return f"{amount:.3g} {unit}"


def _panel_lines(panel: dict, with_targets: bool) -> list[str]:
    lines = []
    for g in panel["groups"]:
        cells = []
        for n in g["nutrients"]:
            if not n["has_data"]:
                continue
            cell = f"{n['nutrient']} {_fmt(n['amount'], n['unit'])}{' (≈)' if n['approx'] else ''}"
            if with_targets and n["pct"] is not None:
                cell += f" = {n['pct']:.0f}% of {'limit' if n['is_limit'] else 'target'}"
            cells.append(cell)
        if cells:
            lines.append(f"- {g['group']}: " + "; ".join(cells))
    return lines


_SOURCE_LABEL = {"foundation": "Foundation", "sr_legacy": "SR Legacy"}


def _release(fdc_id: int) -> str:
    src = (usda.food(fdc_id) or {}).get("source", "")
    return f", {_SOURCE_LABEL.get(src, src)}" if src else ""


def _same_food(a: str, b: str) -> bool:
    return re.findall(r"[a-z]+", a.lower()) == re.findall(r"[a-z]+", b.lower())


def _asked_lines(comp: dict, asked: list[str], grams: float) -> list[str]:
    """The asked-about nutrient(s), answered first with the USDA entry each
    number came from. Order: the matched entry → a sibling entry of the same
    food (store.profile_filled) → the next ranked candidate with identical
    description words that has it → "USDA has no value". Pure arithmetic."""
    if not asked:
        return []
    got = usda.profile_filled(comp["fdc_id"])
    prof = got[0] if got else {}
    out = [f"Asked about, for {grams:g} g:"]
    for name in asked:
        v, fdc = prof.get(name), None
        if v is not None:
            fdc = v.get("from_fdc_id") or comp["fdc_id"]
        else:
            for cand in comp.get("_candidates") or []:
                if cand["fdc_id"] == comp["fdc_id"] or not _same_food(cand["description"], comp["usda_description"]):
                    continue
                v = (usda.profile_per_100g(cand["fdc_id"]) or {}).get(name)
                if v is not None:
                    fdc = cand["fdc_id"]
                    break
        if v is None:
            out.append(f"- {name}: USDA publishes no value for this food in any entry — unknown, not zero.")
            continue
        desc = (usda.food(fdc) or {}).get("description", "")
        approx = " (≈)" if v.get("approx") else ""
        out.append(f"- {name}: {_fmt(v['amount'] * grams / 100.0, v['unit'])}{approx} "
                   f"(from \"{desc}\", FDC {fdc}{_release(fdc)})")
    return out


def chat_nutrition_block(user_text: str, chat_provider: str | None = None) -> str | None:
    if os.environ.get("QUINTACLE_CHAT_NUTRITION", "").strip().lower() in ("off", "0", "false", "no"):
        return None
    if not user_text or not is_food_message(user_text) or not usda.is_installed():
        return None
    try:
        return _block(user_text, chat_provider)
    except Exception as e:  # belt and braces — never break chat
        logger.info("chat nutrition lane failed: %s", e)
        return None


def _block(user_text: str, chat_provider: str | None) -> str | None:
    from ..nodes.logs.nutrition_api import component_from_fdc, current_targets
    from ..nodes.logs.nutrition_targets import REFERENCE_TARGETS

    # A local chat keeps the (index-only) candidate pick local too.
    pick_provider = "local" if chat_provider == "local" and os.environ.get(usda.PICK_PROVIDER_ENV, "") != "off" else None
    comps, unmatched = [], []
    for item in parse_items(user_text)[:8]:
        pick, candidates = usda.match_and_pick(item["food"], pick_provider)
        if pick is None:
            unmatched.append(item["food"])
            continue
        comp = component_from_fdc(pick["fdc_id"], item["grams"], item["food"])
        if comp:
            comps.append({**comp, "_item": item, "_candidates": candidates})
    if not comps:
        return None
    asked = asked_nutrients(user_text)
    targets = current_targets()
    lines = [
        "## Nutrition facts (USDA FoodData Central, per stated amounts)",
        "Computed by code from the offline USDA database. Use THESE numbers for any nutrient listed; do not estimate "
        "nutrients that aren't listed (say USDA has no value for them). Say which USDA entry was assumed for each food "
        "(the owner can correct it) and, for a number taken from another USDA entry of the same food, name that entry; "
        "then suggest logging the meal or composing it as a meal preset to track it.",
    ]
    for c in comps:
        item = c["_item"]
        how = f" — {item['note']}" if item.get("note") else ""
        lines.append(f"\n### {item['food']}: {item['grams']:g} g{how}")
        lines.append(f"USDA match: \"{c['usda_description']}\" (FDC {c['fdc_id']}{_release(c['fdc_id'])})")
        for f in c.get("usda_fill") or []:
            named = [n for n in f["nutrients"] if n in asked] or f["nutrients"][:6]
            more = len(f["nutrients"]) - len(named)
            lines.append(
                f"That entry publishes no value for {', '.join(named)}{f' (+{more} more)' if more > 0 else ''}; those "
                f"numbers come from the same food's other USDA entry \"{f['description']}\" (FDC {f['fdc_id']}"
                f"{_release(f['fdc_id'])}).")
        lines += _asked_lines(c, asked, item["grams"])
        if len(comps) > 1:
            lines += _panel_lines(build_panel([c], {}, REFERENCE_TARGETS), with_targets=False)
    total = build_panel(comps, targets, REFERENCE_TARGETS)
    lines.append("\n### " + ("Total (all items)" if len(comps) > 1 else "Amounts") + " — % of the owner's daily targets where one exists")
    lines += _panel_lines(total, with_targets=True)
    ratio = total["computed"]["omega6_to_omega3"]
    if ratio:
        lines.append(f"- omega-6 : omega-3 ratio ≈ {ratio['value']}:1 ({ratio['label']})")
    epa = total["computed"]["epa_dha"]
    if epa:
        lines.append(f"- EPA + DHA = {epa['amount_mg']:g} mg (reference, not an RDA: {REFERENCE_TARGETS['EPA + DHA']['label']})")
    if unmatched:
        lines.append(f"\nNo USDA match for: {', '.join(unmatched)} — don't invent numbers for these.")
    missing = [n["nutrient"] for g in total["groups"] for n in g["nutrients"] if not n["has_data"]]
    if missing:
        lines.append(f"\nUSDA has no published value for: {', '.join(missing)} — unknown, not zero.")
    lines.append("(≈ = USDA's undifferentiated isomer total used as a stand-in.)")
    return "\n".join(lines)
