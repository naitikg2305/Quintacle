"""Deterministic nutrition-label parser over OCR text (2026-11-06).

The local-first image pipeline's label stage: perception/ocr.py reads the
panel, THIS module turns the text into numbers in code — no model. Only when
the core fields (calories + protein + carbs + fat) can't all be read does the
caller hand the OCR TEXT (never the image) to the local text model
(nutrition_llm.estimate_nutrition_from_label_text), and even then every
value parsed here overrides the model's.

Handles:
  - the US FDA panel (2016 format and the older "Calories from Fat" one):
    serving size + grams, servings per container, calories, total fat,
    saturated, trans, cholesterol, sodium, total carbohydrate, dietary
    fiber, total sugars, "Includes Ng Added Sugars", protein, and every
    vitamin/mineral row — amounts AND %DV;
  - %DV-only rows ("Calcium 20%"): amount = % x the FDA label DV
    (nutrition_targets.FDA_LABEL_DV) — arithmetic in code;
  - OCR noise: O/0 and l/1 next to digits, "rng" for mg, "µg"/"ug" for mcg,
    numbers glued to names/units ("Sodium160mg"), a value pushed onto the
    next line, comma decimals;
  - EU/UK per-100 g panels (stretch): "Energy 1046 kJ / 250 kcal", "Fat",
    "of which saturates", "Carbohydrate", "of which sugars", "Fibre",
    "Protein", "Salt" (sodium = salt / 2.5, in code).

Output shape = nutrition_llm.NutritionEstimateFromImage (basis_amount_g,
protein_g, carbs_g, fat_g, fiber_g, kcal, micros, suggested_name,
from_label=True) plus `field_confidence` {field: 0-1} and `label_dv`
{nutrient: %DV}. basis_amount_g = the serving size in grams (100 for a
per-100 g panel).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .nutrition_targets import FDA_LABEL_DV, to_canonical_unit

# Confidence by HOW a value was obtained (scaled by the OCR line confidence
# when the caller has it).
CONF_STATED = 0.95
CONF_FROM_DV = 0.7
CONF_DERIVED = 0.5
CONF_LLM = 0.5

CORE_FIELDS = ("kcal", "protein_g", "carbs_g", "fat_g")


@dataclass
class LabelValue:
    amount: float
    unit: str
    pct_dv: float | None = None
    conf: float = CONF_STATED
    how: str = "stated"  # stated | from_dv | derived | llm


@dataclass
class LabelParse:
    values: dict[str, LabelValue] = field(default_factory=dict)  # macro keys + Quintacle nutrient names
    serving_size_text: str = ""
    serving_g: float | None = None
    servings_per_container: float | None = None
    per_100g: bool = False

    @property
    def basis_amount_g(self) -> float:
        if self.serving_g:
            return self.serving_g
        return 100.0

    def has(self, key: str) -> bool:
        v = self.values.get(key)
        return v is not None and v.how in ("stated", "from_dv")

    @property
    def core_complete(self) -> bool:
        """calories + protein + carbs + fat all READ off the label (not
        derived) — the "done, no model" bar."""
        return all(self.has(k) for k in CORE_FIELDS)


# ------------------------------------------------------------ normalization


def normalize_ocr(text: str) -> str:
    """Undo the common OCR confusions in numeric contexts; lowercase."""
    t = text or ""
    t = t.replace("•", "\n").replace("·", "\n").replace("|", " ")
    # O <-> 0 / l,I <-> 1 next to digits or before a unit / percent sign.
    t = re.sub(r"(?<=\d)[oO]", "0", t)
    t = re.sub(r"(?<=\d)[oO]", "0", t)  # twice: "1OO"
    t = re.sub(r"(?<![A-Za-z])[oO](?=[.,]?\d|\s*(?:%|g(?![a-z])|mg\b|mcg\b))", "0", t)
    t = re.sub(r"(?<=\d)[lI](?=\d|\s*(?:%|g(?![a-z])|mg\b|mcg\b))", "1", t)
    t = re.sub(r"(?<![A-Za-z])[lI](?=\d)", "1", t)
    t = re.sub(r"[µμ]\s*g\b|(?<=\d)\s*ug\b", "mcg", t)
    t = re.sub(r"(?<=\d)\s*rng\b", "mg", t)
    t = re.sub(r"(?<=\d)\s*mcq\b", "mcg", t)
    t = re.sub(r"(?<=\d)\s*mq\b", "mg", t)
    # Comma decimals (EU "8,5 g") vs thousands ("2,000").
    t = re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", t)
    t = re.sub(r"(?<=\d),(?=\d{1,2}(?!\d))", ".", t)
    return t.lower()


# ------------------------------------------------------------ nutrient specs

_NUM = r"(<\s*)?(\d+(?:\.\d+)?)"
_UNIT = r"(mcg|mg|g|iu)(?![a-z])"
_PCT = r"(?:[ \t]*\(?\s*(\d{1,3}(?:\.\d)?)\s*%)?"
_SEP = r"[\s:\-]*(?:less\s+than\s+|<\s*)?"


@dataclass(frozen=True)
class _Spec:
    key: str  # macro key ("fat_g") or Quintacle nutrient name
    names: tuple[str, ...]  # regexes, tried in order
    unit: str  # canonical unit for macro keys
    dv_key: str | None  # FDA_LABEL_DV key, for %DV-only conversion
    not_after: str | None = None  # regex that must NOT immediately precede the name


_SPECS: tuple[_Spec, ...] = (
    _Spec("fat_g", (r"total\s*fat", r"(?<![a-z])fat(?![a-z])"), "g", "Total Fat", r"(?:satur\w*|sat\.?|trans|poly\w*|mono\w*|from|which)\s*$"),
    _Spec("Saturated Fat", (r"saturated\s*fat", r"sat\.?\s*fat", r"saturates", r"saturated"), "g", "Saturated Fat"),
    _Spec("Trans Fat", (r"trans\s*fat",), "g", None),
    _Spec("Cholesterol", (r"cholest\w*\.?",), "mg", "Cholesterol"),
    _Spec("Sodium", (r"sodium",), "mg", "Sodium"),
    _Spec("carbs_g", (r"total\s*carb\w*\.?", r"(?<![a-z])carbohydrates?(?![a-z])", r"(?<![a-z])carbs?(?![a-z])"), "g", "Total Carbohydrate"),
    _Spec("fiber_g", (r"dietary\s*fib(?:er|re)", r"(?<![a-z])fib(?:er|re)(?![a-z])"), "g", "Dietary Fiber", r"(?:soluble|insoluble)\s*$"),
    _Spec("Added Sugars", (r"added\s*sugars?",), "g", "Added Sugars", r"incl\w*\.?\s*$"),
    _Spec("Total Sugars", (r"total\s*sugars?", r"(?<![a-z])sugars?(?![a-z])"), "g", None, r"(?:added|alcohols?)\s*$"),
    _Spec("protein_g", (r"protein\w*",), "g", "Protein"),
    _Spec("Vitamin D", (r"vit(?:amin|\.)?\s*d\s*3?(?![a-z0-9])",), "mcg", "Vitamin D"),
    _Spec("Vitamin A", (r"vit(?:amin|\.)?\s*a(?![a-z])",), "mcg", "Vitamin A"),
    _Spec("Vitamin C", (r"vit(?:amin|\.)?\s*c(?![a-z])",), "mg", "Vitamin C"),
    _Spec("Vitamin E", (r"vit(?:amin|\.)?\s*e(?![a-z])",), "mg", "Vitamin E"),
    _Spec("Vitamin K", (r"vit(?:amin|\.)?\s*k\s*[12]?(?![a-z0-9])",), "mcg", "Vitamin K"),
    _Spec("Vitamin B12", (r"vit(?:amin|\.)?\s*b\s*12", r"cobalamin"), "mcg", "Vitamin B12"),
    _Spec("Vitamin B6", (r"vit(?:amin|\.)?\s*b\s*6", r"pyridoxine"), "mg", "Vitamin B6"),
    _Spec("Thiamin (B1)", (r"thiamine?", r"vit(?:amin|\.)?\s*b\s*1(?!\d)"), "mg", "Thiamin (B1)"),
    _Spec("Riboflavin (B2)", (r"riboflavin", r"vit(?:amin|\.)?\s*b\s*2(?!\d)"), "mg", "Riboflavin (B2)"),
    _Spec("Niacin (B3)", (r"niacin",), "mg", "Niacin (B3)"),
    _Spec("Folate", (r"folate", r"folic\s*acid"), "mcg", "Folate"),
    _Spec("Biotin", (r"biotin",), "mcg", "Biotin"),
    _Spec("Pantothenic Acid (B5)", (r"pantothenic\s*acid",), "mg", "Pantothenic Acid (B5)"),
    _Spec("Calcium", (r"calcium",), "mg", "Calcium"),
    _Spec("Iron", (r"(?<![a-z])iron(?![a-z])",), "mg", "Iron"),
    _Spec("Potassium", (r"potassium",), "mg", "Potassium"),
    _Spec("Phosphorus", (r"phosphorus",), "mg", "Phosphorus"),
    _Spec("Iodine", (r"iodine",), "mcg", "Iodine"),
    _Spec("Magnesium", (r"magnesium",), "mg", "Magnesium"),
    _Spec("Zinc", (r"(?<![a-z])zinc(?![a-z])",), "mg", "Zinc"),
    _Spec("Selenium", (r"selenium",), "mcg", "Selenium"),
    _Spec("Copper", (r"copper",), "mcg", "Copper"),
    _Spec("Manganese", (r"manganese",), "mg", "Manganese"),
    _Spec("Molybdenum", (r"molybdenum",), "mcg", "Molybdenum"),
    _Spec("Chloride", (r"chloride",), "mg", "Chloride"),
    _Spec("Choline", (r"choline",), "mg", "Choline"),
)

_MACRO_KEYS = {"fat_g", "carbs_g", "fiber_g", "protein_g"}
_G_PER = {"g": 1.0, "mg": 0.001, "mcg": 0.000001}


def _num(lt: str | None, raw: str) -> float:
    """'<1' reads as half the bound — the label only promises "less than"."""
    value = float(raw)
    return value / 2 if lt else value


def _find_value(lines: list[str], spec: _Spec) -> tuple[LabelValue, int] | None:
    """First acceptable occurrence of the nutrient, scanning lines top-down.
    Returns (value, line index). An amount with a unit wins; a bare %DV
    converts through the FDA DV; a name with nothing after it may take its
    value from the start of the next line (OCR split the row)."""
    for i, line in enumerate(lines):
        for name in spec.names:
            for m in re.finditer(name, line):
                if spec.not_after and re.search(spec.not_after, line[max(0, m.start() - 16) : m.start()]):
                    continue
                tail = line[m.end() :]
                nxt = lines[i + 1] if i + 1 < len(lines) else ""
                for cand in (tail, tail + " " + nxt if not re.search(r"\d", tail) else None):
                    if cand is None:
                        continue
                    am = re.match(_SEP + r"" + _NUM + r"\s*" + _UNIT + _PCT, cand)
                    if am:
                        lt = am.group(1) or ("<" if re.match(r"[\s:\-]*(?:less\s+than|<)", cand) else None)
                        amount = _num(lt, am.group(2))
                        unit = am.group(3)
                        pct = float(am.group(4)) if am.group(4) else None
                        return LabelValue(amount, unit, pct), i
                    pm = re.match(r"[\s:\-]*(\d{1,3}(?:\.\d)?)\s*%", cand)
                    if pm and spec.dv_key:
                        dv_amount, dv_unit = FDA_LABEL_DV[spec.dv_key]
                        pct = float(pm.group(1))
                        return LabelValue(round(dv_amount * pct / 100, 4), dv_unit, pct, CONF_FROM_DV, "from_dv"), i
    return None


def _to_unit(value: LabelValue, unit: str) -> float | None:
    if value.unit == unit:
        return value.amount
    if value.unit in _G_PER and unit in _G_PER:
        return value.amount * _G_PER[value.unit] / _G_PER[unit]
    return None


def _calories(lines: list[str]) -> tuple[LabelValue, int] | None:
    for i, line in enumerate(lines):
        m = re.search(r"calories(?!\s*from)(?:\s*per\s*serving)?[\s:\-]*(\d{1,4}(?:\.\d+)?)(?![\d.])(?!\s*%)(?!\s*kj)", line)
        if m:
            return LabelValue(float(m.group(1)), "kcal"), i
        if re.search(r"calories(?!\s*from)\s*$", line) and i + 1 < len(lines):
            m2 = re.match(r"\s*(\d{1,4})(?!\s*%)\b", lines[i + 1])
            if m2:
                return LabelValue(float(m2.group(1)), "kcal"), i + 1
    for i, line in enumerate(lines):
        m = re.search(r"(\d+(?:\.\d+)?)\s*kcal", line)
        if m:
            return LabelValue(float(m.group(1)), "kcal"), i
    for i, line in enumerate(lines):  # EU energy row with kJ only — convert in code
        m = re.search(r"energy[\s:\-]*(\d+(?:\.\d+)?)\s*kj", line)
        if m:
            return LabelValue(round(float(m.group(1)) / 4.184, 1), "kcal", None, CONF_DERIVED, "derived"), i
    return None


def _serving(lines: list[str], parse: LabelParse) -> None:
    for i, line in enumerate(lines):
        m = re.search(r"serv(?:ing|\.)\s*size[\s:\-]*(.*)$", line)
        if m:
            text = m.group(1).strip() or (lines[i + 1].strip() if i + 1 < len(lines) else "")
            parse.serving_size_text = text
            g = re.search(r"(\d+(?:\.\d+)?)\s*(g|ml)(?![a-z])", text)
            if g:
                parse.serving_g = float(g.group(1))
            break
    for line in lines:
        m = re.search(r"(?:about\s*)?(\d+(?:\.\d+)?)\s*servings?\s*per\s*(?:container|package|pack)", line) or re.search(
            r"servings?\s*per\s*(?:container|package|pack)[\s:\-]*(?:about\s*)?(\d+(?:\.\d+)?)", line
        )
        if m:
            parse.servings_per_container = float(m.group(1))
            break
    if parse.serving_g is None:
        for line in lines:
            if re.search(r"per\s*100\s*(?:g|ml)\b|/\s*100\s*(?:g|ml)\b|100\s*g\s*(?:provide|contain)", line):
                parse.per_100g = True
                break
        if not parse.per_100g:  # EU "per serving (30g)"
            for line in lines:
                m = re.search(r"per\s*(?:serving|portion)\s*\(?\s*(\d+(?:\.\d+)?)\s*g\b", line)
                if m:
                    parse.serving_g = float(m.group(1))
                    break


def parse_label(text: str, line_confs: list[float] | None = None) -> LabelParse:
    """Every number the label states, read in code. `line_confs` (aligned
    with text.splitlines(), from the OCR result) scales confidences."""
    raw_lines = (text or "").splitlines()
    lines = [normalize_ocr(ln) for ln in raw_lines]
    parse = LabelParse()
    _serving(lines, parse)

    def conf_at(i: int) -> float:
        if line_confs and 0 <= i < len(line_confs):
            return max(0.0, min(1.0, float(line_confs[i])))
        return 1.0

    cal = _calories(lines)
    if cal:
        value, i = cal
        value.conf = round(value.conf * conf_at(i), 3)
        parse.values["kcal"] = value

    # "Includes 10g Added Sugars 20%" — the amount comes BEFORE the name.
    for i, line in enumerate(lines):
        m = re.search(r"incl\w*\.?\s*(<\s*)?(\d+(?:\.\d+)?)\s*g(?![a-z])\s*(?:of\s*)?added\s*sugars?" + _PCT, line)
        if m:
            pct = float(m.group(3)) if m.group(3) else None
            parse.values["Added Sugars"] = LabelValue(_num(m.group(1), m.group(2)), "g", pct, round(CONF_STATED * conf_at(i), 3))
            break

    for spec in _SPECS:
        if spec.key in parse.values:
            continue
        found = _find_value(lines, spec)
        if not found:
            continue
        value, i = found
        if value.unit == "iu":
            if value.pct_dv is None or not spec.dv_key:
                continue  # IU can't be converted without the vitamin's form — skip rather than mislabel
            dv_amount, dv_unit = FDA_LABEL_DV[spec.dv_key]
            value = LabelValue(round(dv_amount * value.pct_dv / 100, 4), dv_unit, value.pct_dv, CONF_FROM_DV, "from_dv")
        value.conf = round(value.conf * conf_at(i), 3)
        parse.values[spec.key] = value

    # EU salt -> sodium (sodium = salt / 2.5), only when sodium isn't printed.
    if "Sodium" not in parse.values:
        for i, line in enumerate(lines):
            m = re.search(r"(?<![a-z])salt[\s:\-]*(<\s*)?(\d+(?:\.\d+)?)\s*(g|mg)(?![a-z])", line)
            if m:
                grams = _num(m.group(1), m.group(2)) * (0.001 if m.group(3) == "mg" else 1)
                parse.values["Sodium"] = LabelValue(round(grams / 2.5 * 1000, 1), "mg", None, round(CONF_DERIVED * conf_at(i), 3), "derived")
                break

    _plausibility(parse)
    return parse


def _plausibility(parse: LabelParse) -> None:
    """Code-side sanity: an absurd value (OCR merged two numbers) is dropped;
    calories that disagree with 4/4/9 x the macros lose confidence (the
    printed number is kept — the label is the authority, it may just be
    rounded)."""
    limit = (parse.serving_g or 100) * 1.1 + 1
    for key in ("fat_g", "carbs_g", "protein_g", "fiber_g", "Total Sugars", "Added Sugars", "Saturated Fat"):
        v = parse.values.get(key)
        if v is None:
            continue
        grams = _to_unit(v, "g")
        if grams is not None and grams > max(limit, 150):
            del parse.values[key]
    kcal = parse.values.get("kcal")
    if kcal is not None and kcal.amount > 3000:
        del parse.values["kcal"]
        kcal = None
    macros = [parse.values.get(k) for k in ("protein_g", "carbs_g", "fat_g")]
    if all(m is not None for m in macros):
        p, c, f = (_to_unit(m, "g") or 0 for m in macros)
        computed = 4 * p + 4 * c + 9 * f
        if kcal is None:
            parse.values["kcal"] = LabelValue(round(computed, 1), "kcal", None, CONF_DERIVED, "derived")
        elif abs(kcal.amount - computed) > max(25.0, 0.25 * computed):
            kcal.conf = round(min(kcal.conf, 0.6), 3)


# ------------------------------------------------------------ output


def to_estimate(parse: LabelParse, suggested_name: str) -> dict:
    """The NutritionEstimateFromImage-shaped dict the photo lane produces,
    from_label=True, plus field_confidence / label_dv / serving metadata."""
    out: dict = {
        "basis_amount_g": parse.basis_amount_g,
        "suggested_name": suggested_name,
        "from_label": True,
    }
    confidence: dict[str, float] = {}
    for key in ("protein_g", "carbs_g", "fat_g", "fiber_g"):
        v = parse.values.get(key)
        grams = _to_unit(v, "g") if v is not None else None
        out[key] = round(grams, 3) if grams is not None else 0.0
        confidence[key] = v.conf if (v is not None and grams is not None) else 0.0
    kcal = parse.values.get("kcal")
    out["kcal"] = kcal.amount if kcal else 0.0
    confidence["kcal"] = kcal.conf if kcal else 0.0
    micros = []
    label_dv: dict[str, float] = {}
    for key, v in parse.values.items():
        if key in _MACRO_KEYS or key == "kcal":
            continue
        amount, unit = to_canonical_unit(v.amount, v.unit, key)
        micros.append({"nutrient": key, "amount": round(amount, 4), "unit": unit})
        confidence[key] = v.conf
        if v.pct_dv is not None:
            label_dv[key] = v.pct_dv
    for key in ("fat_g", "carbs_g", "fiber_g", "protein_g"):
        v = parse.values.get(key)
        if v is not None and v.pct_dv is not None:
            label_dv[key] = v.pct_dv
    out["micros"] = micros
    out["field_confidence"] = confidence
    out["label_dv"] = label_dv
    out["serving_size_text"] = parse.serving_size_text
    out["servings_per_container"] = parse.servings_per_container
    out["per_100g"] = parse.per_100g
    return out


def overlay_parsed(model_fields: dict, parse: LabelParse) -> dict:
    """Merge a local-LLM label read with the deterministic parse: every
    value code READ wins; the model only fills what code couldn't; model
    values are tagged CONF_LLM."""
    parsed = to_estimate(parse, model_fields.get("suggested_name", ""))
    out = {**model_fields, "from_label": True}
    conf = {}
    for key in ("protein_g", "carbs_g", "fat_g", "fiber_g", "kcal"):
        if parsed["field_confidence"].get(key, 0) > 0:
            out[key] = parsed[key]
            conf[key] = parsed["field_confidence"][key]
        else:
            conf[key] = CONF_LLM
    by_name = {m["nutrient"]: m for m in (model_fields.get("micros") or [])}
    for m in parsed["micros"]:
        by_name[m["nutrient"]] = m
    out["micros"] = list(by_name.values())
    for name in by_name:
        conf[name] = parsed["field_confidence"].get(name, CONF_LLM)
    if parse.serving_g:
        out["basis_amount_g"] = parse.serving_g
    elif parse.per_100g:
        out["basis_amount_g"] = 100.0
    out["field_confidence"] = conf
    out["label_dv"] = parsed["label_dv"]
    out["serving_size_text"] = parsed["serving_size_text"]
    out["servings_per_container"] = parsed["servings_per_container"]
    out["per_100g"] = parsed["per_100g"]
    return out


_LABEL_WORDS_RE = re.compile(
    r"nutrition|serving|calorie|daily value|total|fat|sodium|protein|carb|sugar|fib(?:er|re)|vitamin|calcium|iron|potassium|"
    r"ingredients|cholesterol|contains|%|\d",
    re.IGNORECASE,
)


def guess_product_name(lines: list[tuple[str, tuple, float]] | None) -> str:
    """Product name heuristic over OCR lines (text, box, conf): the tallest
    line that isn't label-panel vocabulary — usually the brand/product on a
    front-of-package shot. '' when nothing qualifies."""
    best, best_h = "", 0.0
    for text, box, _conf in lines or []:
        clean = text.strip()
        if len(re.findall(r"[A-Za-z]", clean)) < 3 or _LABEL_WORDS_RE.search(clean):
            continue
        h = float(box[3]) if box else 0.0
        if h > best_h:
            best, best_h = clean, h
    return best[:60]


__all__ = [
    "CORE_FIELDS",
    "LabelParse",
    "LabelValue",
    "guess_product_name",
    "normalize_ocr",
    "overlay_parsed",
    "parse_label",
    "to_estimate",
]
