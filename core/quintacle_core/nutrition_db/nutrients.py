"""The one map from USDA FoodData Central nutrient ids to Quintacle nutrient
names (2026-11-05). Everything else (the db builder, the per-100 g profile
read, the UI grouping) reads from here, so a nutrient is added in one place.

Each nutrient lists its USDA sources in priority order. A source is
(fdc_nutrient_id, factor, approx). `factor` converts the USDA unit into the
Quintacle unit (Copper is published in MG, Quintacle stores mcg, so ×1000).
`approx` marks a documented stand-in: SR Legacy splits 18:3 into its n-3
isomer (ALA, id 1404) for only ~2k of ~7.8k foods; the rest carry just the
undifferentiated 18:3 total (id 1270), which in ordinary foods is
overwhelmingly ALA. Same story for linoleic acid (1316 vs 18:2 total 1269).
The UI shows an "≈" on approximated values instead of hiding the gap.

`sum_of` (flavonoid classes, lutein+zeaxanthin): when the food has no
published class total, the class is the sum of the individual compounds
that ARE published — the same definition USDA's flavonoid tables use.
"""
from __future__ import annotations

from dataclasses import dataclass, field

GROUPS = ["Macros", "Vitamins", "Minerals", "Fatty acids", "Flavonoids", "Carotenoids", "Other"]


@dataclass(frozen=True)
class NutrientDef:
    name: str
    unit: str  # Quintacle's canonical unit: g | mg | mcg | kcal
    group: str
    sources: tuple[tuple[int, float, bool], ...] = ()
    sum_of: tuple[int, ...] = field(default_factory=tuple)
    # Macros that live in the preset's own columns (protein_g, …) rather
    # than in the micros list.
    macro_field: str | None = None


def _s(*ids: int, factor: float = 1.0) -> tuple[tuple[int, float, bool], ...]:
    """Exact sources, same factor."""
    return tuple((i, factor, False) for i in ids)


# Flavonoid compound ids (FDC nutrient.id; the USDA Flavonoid Database uses
# the SR nutrient_nbr, mapped in FLAV_NBR_TO_ID below).
_ANTHOCYANIDINS = (1349, 1357, 1358, 1359, 1360, 1361)  # cyanidin, delphinidin, malvidin, pelargonidin, peonidin, petunidin
_FLAVAN_3_OLS = (1364, 1365, 1366, 1367, 1368, 1396, 1397, 1398, 1370, 1393, 1394, 1395, 1371)  # catechins, gallocatechins, theaflavins, thearubigins
_FLAVANONES = (1373, 1374, 1377)  # eriodictyol, hesperetin, naringenin
_FLAVONES = (1379, 1382)  # apigenin, luteolin
_FLAVONOLS = (1387, 1388, 1390, 1391)  # isorhamnetin, kaempferol, myricetin, quercetin
_ISOFLAVONES = (1340, 1341, 1342)  # daidzein, genistein, glycitein

NUTRIENTS: list[NutrientDef] = [
    # --- Macros (preset columns) ---
    NutrientDef("Energy", "kcal", "Macros", _s(1008, 2047, 2048), macro_field="kcal"),
    NutrientDef("Protein", "g", "Macros", _s(1003), macro_field="protein_g"),
    NutrientDef("Carbohydrates", "g", "Macros", _s(1005, 1050), macro_field="carbs_g"),
    NutrientDef("Fat", "g", "Macros", _s(1004, 1085), macro_field="fat_g"),
    NutrientDef("Fiber", "g", "Macros", _s(1079, 2033), macro_field="fiber_g"),
    NutrientDef("Total Sugars", "g", "Macros", _s(2000, 1063)),
    NutrientDef("Added Sugars", "g", "Macros", _s(1235)),
    # --- Vitamins (the original tracked set) ---
    NutrientDef("Vitamin A", "mcg", "Vitamins", _s(1106)),
    NutrientDef("Vitamin C", "mg", "Vitamins", _s(1162)),
    NutrientDef("Vitamin D", "mcg", "Vitamins", _s(1114) + ((1110, 0.025, False),)),  # IU → mcg is exact (÷40)
    NutrientDef("Vitamin E", "mg", "Vitamins", _s(1109)),
    NutrientDef("Vitamin K", "mcg", "Vitamins", _s(1185)),
    NutrientDef("Vitamin B6", "mg", "Vitamins", _s(1175)),
    NutrientDef("Vitamin B12", "mcg", "Vitamins", _s(1178)),
    NutrientDef("Folate", "mcg", "Vitamins", _s(1190) + ((1177, 1.0, True),)),  # DFE; total folate as stand-in
    NutrientDef("Thiamin (B1)", "mg", "Vitamins", _s(1165)),
    NutrientDef("Riboflavin (B2)", "mg", "Vitamins", _s(1166)),
    NutrientDef("Niacin (B3)", "mg", "Vitamins", _s(1167)),
    NutrientDef("Biotin", "mcg", "Vitamins", _s(1176)),
    NutrientDef("Pantothenic Acid (B5)", "mg", "Vitamins", _s(1170)),
    NutrientDef("Choline", "mg", "Vitamins", _s(1180)),
    # --- Minerals ---
    NutrientDef("Calcium", "mg", "Minerals", _s(1087)),
    NutrientDef("Iron", "mg", "Minerals", _s(1089)),
    NutrientDef("Magnesium", "mg", "Minerals", _s(1090)),
    NutrientDef("Zinc", "mg", "Minerals", _s(1095)),
    NutrientDef("Selenium", "mcg", "Minerals", _s(1103)),
    NutrientDef("Potassium", "mg", "Minerals", _s(1092)),
    NutrientDef("Sodium", "mg", "Minerals", _s(1093)),
    NutrientDef("Phosphorus", "mg", "Minerals", _s(1091)),
    NutrientDef("Copper", "mcg", "Minerals", _s(1098, factor=1000.0)),  # USDA publishes mg
    NutrientDef("Iodine", "mcg", "Minerals", _s(1100)),
    NutrientDef("Manganese", "mg", "Minerals", _s(1101)),
    NutrientDef("Molybdenum", "mcg", "Minerals", _s(1102)),
    NutrientDef("Chloride", "mg", "Minerals", _s(1088)),
    # --- Fatty acids ---
    NutrientDef("Saturated Fat", "g", "Fatty acids", _s(1258)),
    NutrientDef("Monounsaturated Fat", "g", "Fatty acids", _s(1292)),
    NutrientDef("Polyunsaturated Fat", "g", "Fatty acids", _s(1293)),
    NutrientDef("Trans Fat", "g", "Fatty acids", _s(1257)),
    NutrientDef("ALA (omega-3)", "g", "Fatty acids", _s(1404) + ((1270, 1.0, True),)),
    NutrientDef("EPA (omega-3)", "g", "Fatty acids", _s(1278)),
    NutrientDef("DPA (omega-3)", "g", "Fatty acids", _s(1280)),
    NutrientDef("DHA (omega-3)", "g", "Fatty acids", _s(1272)),
    NutrientDef("Linoleic acid (omega-6)", "g", "Fatty acids", _s(1316) + ((1269, 1.0, True),)),
    # --- Flavonoids (mg, USDA Flavonoid Database classes) ---
    NutrientDef("Flavan-3-ols", "mg", "Flavonoids", sum_of=_FLAVAN_3_OLS),
    NutrientDef("Flavonols", "mg", "Flavonoids", _s(1386), sum_of=_FLAVONOLS),
    NutrientDef("Flavones", "mg", "Flavonoids", _s(1378), sum_of=_FLAVONES),
    NutrientDef("Flavanones", "mg", "Flavonoids", _s(1372), sum_of=_FLAVANONES),
    NutrientDef("Anthocyanidins", "mg", "Flavonoids", _s(1348), sum_of=_ANTHOCYANIDINS),
    NutrientDef("Isoflavones", "mg", "Flavonoids", _s(1343), sum_of=_ISOFLAVONES),
    # --- Carotenoids (mcg) ---
    NutrientDef("Beta-carotene", "mcg", "Carotenoids", _s(1107)),
    NutrientDef("Alpha-carotene", "mcg", "Carotenoids", _s(1108)),
    NutrientDef("Lycopene", "mcg", "Carotenoids", _s(1122)),
    NutrientDef("Lutein + zeaxanthin", "mcg", "Carotenoids", _s(1123), sum_of=(1121, 1119)),
    NutrientDef("Beta-cryptoxanthin", "mcg", "Carotenoids", _s(1120)),
    # --- Other ---
    NutrientDef("Cholesterol", "mg", "Other", _s(1253)),
    NutrientDef("Caffeine", "mg", "Other", _s(1057)),
    NutrientDef("Theobromine", "mg", "Other", _s(1058)),
    NutrientDef("Water", "g", "Other", _s(1051)),
]

BY_NAME: dict[str, NutrientDef] = {n.name: n for n in NUTRIENTS}
MACRO_FIELDS: dict[str, str] = {n.macro_field: n.name for n in NUTRIENTS if n.macro_field}
UNITS: dict[str, str] = {n.name: n.unit for n in NUTRIENTS}
GROUP_OF: dict[str, str] = {n.name: n.group for n in NUTRIENTS}

# Every FDC nutrient id any definition reads — the builder keeps only these
# rows of food_nutrient.csv (that filter is most of the size win).
USED_USDA_IDS: frozenset[int] = frozenset(
    {sid for n in NUTRIENTS for sid, _, _ in n.sources} | {cid for n in NUTRIENTS for cid in n.sum_of}
)

# USDA Database for the Flavonoid Content of Selected Foods (Release 3.3)
# keys its values by SR nutrient number; these are the matching FDC ids.
FLAV_NBR_TO_ID: dict[int, int] = {
    710: 1340, 711: 1341, 712: 1342, 713: 1343, 730: 1348, 731: 1349, 741: 1357, 742: 1358,
    743: 1359, 745: 1360, 746: 1361, 749: 1364, 750: 1365, 751: 1366, 752: 1367, 753: 1368,
    755: 1370, 756: 1371, 757: 1372, 758: 1373, 759: 1374, 762: 1377, 768: 1378, 770: 1379,
    773: 1382, 784: 1386, 785: 1387, 786: 1388, 788: 1390, 789: 1391, 791: 1393, 792: 1394,
    793: 1395, 794: 1396, 795: 1397, 796: 1398,
}


def resolve(raw: dict[int, float]) -> dict[str, tuple[float, bool]]:
    """{fdc_nutrient_id: amount in USDA unit} for ONE food → {Quintacle name:
    (amount in Quintacle unit, approx)}. Pure arithmetic; a nutrient with no
    usable source is simply absent (unknown ≠ zero)."""
    out: dict[str, tuple[float, bool]] = {}
    for n in NUTRIENTS:
        for sid, factor, approx in n.sources:
            if sid in raw:
                out[n.name] = (raw[sid] * factor, approx)
                break
        else:
            present = [raw[c] for c in n.sum_of if c in raw]
            if present:
                out[n.name] = (sum(present), False)
    return out
