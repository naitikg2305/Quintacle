"""The full nutrient panel, computed in code (2026-11-05).

Input: components already scaled to what was eaten / planned —
    {"name", "source", "macros": {kcal, protein_g, carbs_g, fat_g, fiber_g},
     "micros": [{nutrient, amount, unit, source?, approx?}]}
plus the owner's targets. Output: grouped nutrients (Macros · Vitamins ·
Minerals · Fatty acids · Flavonoids · Carotenoids · Other) with total,
% of target where an official one exists, labelled reference ranges where
only guidance exists, source badge, coverage (how many components actually
had data — unknown is never silently 0) and per-component contributions
("Calcium: 62% from Greek yogurt"). Plus the computed omega-6:omega-3 ratio
and EPA+DHA figure. No model anywhere near this.
"""
from __future__ import annotations

from .nutrients import GROUPS, MACRO_FIELDS, NUTRIENTS

OMEGA3 = ("ALA (omega-3)", "EPA (omega-3)", "DPA (omega-3)", "DHA (omega-3)")
OMEGA6 = ("Linoleic acid (omega-6)",)


def _merge(sources: set[str]) -> str:
    sources = {s for s in sources if s}
    if not sources:
        return ""
    return next(iter(sources)) if len(sources) == 1 else "mixed"


def build_panel(components: list[dict], targets: dict[str, dict], references: dict[str, dict]) -> dict:
    """targets: {nutrient: {amount, unit, kind, is_limit}} (official only).
    references: {name: {low, high, unit, label}} (guidance, labelled)."""
    order = [n.name for n in NUTRIENTS]
    units = {n.name: n.unit for n in NUTRIENTS}
    group_of = {n.name: n.group for n in NUTRIENTS}
    acc: dict[str, dict] = {}

    def add(nutrient: str, unit: str, amount: float, comp: dict, source: str, approx: bool) -> None:
        row = acc.setdefault(nutrient, {"unit": unit, "amount": 0.0, "sources": set(), "approx": False, "by": {}})
        row["amount"] += amount
        row["sources"].add(source)
        row["approx"] = row["approx"] or approx
        by = row["by"].setdefault(comp["name"], {"amount": 0.0, "sources": set()})
        by["amount"] += amount
        by["sources"].add(source)

    for comp in components:
        comp_source = comp.get("source") or "estimated"
        for field, name in MACRO_FIELDS.items():
            value = (comp.get("macros") or {}).get(field)
            if value is not None:
                add(name, units[name], float(value), comp, comp_source, False)
        for m in comp.get("micros") or []:
            add(m["nutrient"], m.get("unit", ""), float(m["amount"]), comp, m.get("source") or comp_source, bool(m.get("approx")))

    n_components = len(components)
    groups: dict[str, list[dict]] = {g: [] for g in GROUPS}
    names = order + sorted(n for n in acc if n not in units)
    for name in names:
        row = acc.get(name)
        amount = row["amount"] if row else 0.0
        target = targets.get(name)
        ref = references.get(name)
        entry = {
            "nutrient": name,
            "unit": row["unit"] if row else units.get(name, ""),
            "amount": round(amount, 4),
            "has_data": row is not None,
            "approx": bool(row and row["approx"]),
            "source": _merge(row["sources"]) if row else "",
            "coverage": {"with_data": len(row["by"]) if row else 0, "of": n_components},
            "target": None,
            "pct": None,
            "is_limit": False,
            "reference": None,
            "contributions": [],
        }
        if target and target.get("amount"):
            entry["target"] = {"amount": target["amount"], "unit": target["unit"], "kind": target.get("kind", "RDA")}
            entry["pct"] = round(amount / target["amount"] * 100, 1)
            entry["is_limit"] = bool(target.get("is_limit"))
        elif ref:
            entry["reference"] = ref
        if row and amount > 0:
            entry["contributions"] = sorted(
                (
                    {"name": who, "amount": round(v["amount"], 4), "pct": round(v["amount"] / amount * 100, 1),
                     "source": _merge(v["sources"])}
                    for who, v in row["by"].items() if v["amount"] > 0
                ),
                key=lambda c: -c["amount"],
            )
        groups[group_of.get(name, "Other")].append(entry)

    def total(name: str) -> float | None:
        return acc[name]["amount"] if name in acc else None

    o3 = [total(n) for n in OMEGA3]
    o6 = [total(n) for n in OMEGA6]
    omega3 = sum(v for v in o3 if v is not None)
    omega6 = sum(v for v in o6 if v is not None)
    ratio = None
    if any(v is not None for v in o3) and any(v is not None for v in o6) and omega3 > 0:
        ratio = {
            "value": round(omega6 / omega3, 2),
            "omega6_g": round(omega6, 4),
            "omega3_g": round(omega3, 4),
            "label": "linoleic acid : (ALA + EPA + DPA + DHA) — no official target",
        }
    epa, dha = total("EPA (omega-3)"), total("DHA (omega-3)")
    epa_dha = None
    if epa is not None or dha is not None:
        epa_dha = {"amount_mg": round(((epa or 0) + (dha or 0)) * 1000, 1), "reference": references.get("EPA + DHA")}

    return {
        "groups": [{"group": g, "nutrients": groups[g]} for g in GROUPS if groups[g]],
        "computed": {"omega6_to_omega3": ratio, "epa_dha": epa_dha},
        "components": [{"name": c["name"], "source": c.get("source") or "estimated", **({"quantity_g": c["quantity_g"]} if "quantity_g" in c else {})} for c in components],
    }
