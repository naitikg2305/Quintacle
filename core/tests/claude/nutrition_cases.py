"""The NUTRITION checks, written once and run by BOTH live suites (each suite's
test module binds `client` + `provider`). Every expected number is computed
from the sandbox's copy of the owner's real USDA db (nutrition_db.store) —
the principle under test is "numbers only ever come from the db; a model at
most picks WHICH food". Expectations are fixed from intent; a failure is a
finding about the model/code, never a reason to re-fit the expectation."""
import math
import re

from tests.claude import cases
from tests.claude.harness import drop, first

INGREDIENT_TEXT = "ingredient: 100g raw broccoli"  # "ingredient:" -> ingredient_preset (drop_router.PREFIX_TYPES)

# Three common foods in grams. Named explicitly so the proposed meal can't
# fuzzy-collide with the seeded "Chicken rice bowl"/"Greek yogurt bowl"
# presets (the additive lane drops a proposal whose name already exists).
MEAL_PREP = (
    "Meal prep plan, call it Tuesday lunch box:\n"
    "- 200g chicken breast\n- 150g cooked white rice\n- 170g plain greek yogurt"
)
MEAL_PREP_FOODS = {  # key words the USDA match must carry -> grams stated
    ("chicken", "breast"): 200,
    ("rice", "cooked"): 150,  # "cooked" matters: raw rice is ~3x the kcal
    ("yogurt", "greek"): 170,
}

CHAT_QUESTION = "how much selenium is in 200g of lamb?"
CHAT_GRAMS = 200
CHAT_MODEL = {"local": "local:qwen3:8b", "cloud": "max:sonnet"}
# "lamb" means the meat; an organ row is a wrong pick, not an alternative answer.
_OFFAL = ("liver", "heart", "kidney", "testes", "tongue", "brain", "sweetbread", "lung", "spleen", "pancreas")
_MACROS = ("protein_g", "carbs_g", "fat_g", "fiber_g", "kcal")


def _usda():
    from quintacle_core.nutrition_db import store  # lazy: env (QUINTACLE_USDA_DB) is set by make_client

    assert store.is_installed(), f"USDA db missing at {store.db_path()} — harness should have copied it"
    return store


def _micros(comp: dict) -> list[dict]:
    return comp.get("new_ingredient_micros") or comp.get("micros") or []


def _micro(micros: list[dict], nutrient: str) -> float | None:
    for m in micros:
        if m.get("nutrient") == nutrient:
            return float(m.get("amount") or 0)
    return None


def _close(a: float, b: float) -> bool:
    return math.isclose(float(a or 0), float(b or 0), rel_tol=1e-4, abs_tol=0.01)


def _assert_numbers_from_db(entry: dict, grams: float) -> None:
    """source=usda must mean the numbers ARE the db's, scaled to the grams."""
    want = _usda().preset_from_usda(int(entry["fdc_id"]), grams)
    assert want is not None, f"fdc_id {entry['fdc_id']} not in the USDA db"
    bad = {k: (entry.get(k), want[k]) for k in _MACROS if not _close(entry.get(k), want[k])}
    assert not bad, f"{entry.get('name') or entry.get('suggested_name')}: macros differ from USDA (got, db): {bad}"
    got_micros = {m["nutrient"]: m["amount"] for m in _micros(entry)}
    for m in want["micros"]:
        assert m["nutrient"] in got_micros, f"USDA micro {m['nutrient']} missing from proposal"
        assert _close(got_micros[m["nutrient"]], m["amount"]), (m["nutrient"], got_micros[m["nutrient"]], m["amount"])


def _composition(c, text: str, provider: str) -> dict:
    r = drop(c, text=text, provider=provider)
    return first(r, "meal_composition")


def check_broccoli_ingredient(c, provider):
    """A plain whole food has an authoritative USDA row, so the preset must be USDA-sourced (raw broccoli, real vitamin C), never a model estimate."""
    r = drop(c, text=INGREDIENT_TEXT, provider=provider)
    e = first(r, "ingredient_preset")
    assert e.get("source") == "usda", f"source={e.get('source')!r} desc={e.get('usda_description')!r}"
    assert isinstance(e.get("fdc_id"), int), e.get("fdc_id")
    desc = (e.get("usda_description") or "").lower()
    assert "broccoli" in desc and "raw" in desc, desc  # the user said raw — a cooked row is a wrong pick
    assert float(e.get("basis_amount_g") or 0) == 100, e.get("basis_amount_g")
    vit_c = _micro(e.get("micros") or [], "Vitamin C")
    assert vit_c is not None and vit_c > 0, f"Vitamin C={vit_c}; micros={[m.get('nutrient') for m in e.get('micros') or []]}"
    assert all(m.get("source") == "usda" for m in e["micros"]), "a USDA preset's micros must all be tagged usda"
    _assert_numbers_from_db(e, 100)
    return r


def check_meal_prep_usda(c, provider):
    """Rice, chicken breast and greek yogurt all exist in USDA, so each component must be USDA-sourced at the stated grams and the totals must be their exact sum."""
    comp = _composition(c, MEAL_PREP, provider)
    comps = comp.get("components") or []
    assert len(comps) == 3, f"expected 3 components, got {[(x.get('name'), x.get('quantity_g')) for x in comps]}"
    for words, grams in MEAL_PREP_FOODS.items():
        hits = [x for x in comps if all(w in (x.get("usda_description") or "").lower() for w in words)]
        assert hits, (f"no USDA component matching {words}; got "
                      f"{[(x.get('name'), x.get('source'), x.get('usda_description')) for x in comps]}")
        x = hits[0]
        assert x.get("source") == "usda" and isinstance(x.get("fdc_id"), int), (x.get("name"), x.get("source"))
        assert abs(float(x["quantity_g"]) - grams) <= 1, f"{x['name']}: quantity {x['quantity_g']} != stated {grams}g"
        _assert_numbers_from_db(x, float(x["quantity_g"]))
    totals = comp.get("totals") or {}
    for k in _MACROS:
        want = sum(float(x.get(k) or 0) for x in comps)
        assert _close(totals.get(k), want), f"totals[{k}]={totals.get(k)} but components sum to {want}"
    return comp


def check_lamb_meal_micros(c, provider):
    """USDA lamb shoulder carries omega-3 (ALA) and calcium, so a composed lamb meal must surface both from the db, not drop or guess them."""
    comp = _composition(c, cases.MEAL_PLAN, provider)
    comps = comp.get("components") or []
    lamb = [x for x in comps if "lamb" in (x.get("usda_description") or "").lower()]
    assert lamb, f"no USDA lamb component; got {[(x.get('name'), x.get('source'), x.get('usda_description')) for x in comps]}"
    x = lamb[0]
    desc = x["usda_description"].lower()
    assert x.get("source") == "usda", x.get("source")
    assert "shoulder" in desc and not any(o in desc for o in _OFFAL), desc  # the plan says lamb shoulder
    assert abs(float(x["quantity_g"]) - 200) <= 1, x["quantity_g"]
    micros = _micros(x)
    omega3 = {m["nutrient"]: m["amount"] for m in micros if "omega-3" in m.get("nutrient", "")}
    assert any(float(v or 0) > 0 for v in omega3.values()), f"no non-zero omega-3 in lamb micros: {omega3}"
    calcium = _micro(micros, "Calcium")
    assert calcium is not None and calcium > 0, f"Calcium={calcium}"
    assert all(m.get("source") == "usda" for m in micros), "USDA component micros must be tagged usda"
    _assert_numbers_from_db(x, float(x["quantity_g"]))
    return comp


def expected_lamb_selenium() -> dict[str, float]:
    """{USDA description: mcg selenium in CHAT_GRAMS} for the lamb-meat rows
    the chat lane can pick from (match_food's default top 8, offal excluded,
    rows with a published selenium value only)."""
    store = _usda()
    out = {}
    for cand in store.match_food("lamb"):
        desc = cand["description"].lower()
        if "lamb" not in desc or any(o in desc for o in _OFFAL):
            continue
        se = (store.profile_per_100g(cand["fdc_id"]) or {}).get("Selenium")
        if se and se["amount"]:
            out[cand["description"]] = round(se["amount"] * CHAT_GRAMS / 100, 2)
    assert out, "no lamb row with a selenium value in the USDA db"
    return out


_SE_NUM = re.compile(r"(\d+(?:\.\d+)?)\s*\**\s*(?:mcg|µg|μg|ug|micrograms?)\b", re.I)


def check_chat_lamb_selenium(c, provider):
    """The chat nutrition lane hands the model USDA-computed selenium for 200 g of lamb, so the reply must cite that number (±15%), not a guess or "unknown"."""
    expected = expected_lamb_selenium()
    r = c.post("/kb/chat", json={"messages": [{"role": "user", "content": CHAT_QUESTION}],
                                 "model": CHAT_MODEL[provider], "use_kb": False, "web": False})
    assert r.status_code == 200, f"/kb/chat {r.status_code}: {r.text[:400]}"
    reply = r.json()["reply"]
    segments = [s for s in re.split(r"(?<=[.!?])\s+|\n", reply) if "selen" in s.lower()]
    cited = [float(m) for s in segments for m in _SE_NUM.findall(s)]
    ok = [v for v in cited if any(abs(v - want) <= 0.15 * want for want in expected.values())]
    assert ok, f"no selenium figure within 15% of USDA {expected}; cited={cited}; reply={reply[:800]!r}"
    return reply


ALL = [check_broccoli_ingredient, check_meal_prep_usda, check_lamb_meal_micros, check_chat_lamb_selenium]

# Fully deterministic once the prefix routes it: USDA numbers, at most a
# (local/auto) index pick. The prefix lane passes no provider, so a Max call
# is not expected there — every other check must reach Claude in the Max suite.
NO_CLOUD_CALL = {check_broccoli_ingredient}
