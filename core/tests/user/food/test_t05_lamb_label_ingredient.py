"""T5 (TESTING-LOG.md): the owner drops a photo of his lamb's nutrition label and saves it as an
ingredient, to build a breakfast meal from it next (2026-11-17).

The photo: files/food/lamb-label-2026-11-17/13455__2.jpg (an AVIF image with a .jpg name), the
back of a pack of New Zealand Spring Lamb "HALAL GROUND LAMB, 85% LEAN / 15% FAT". Serving 4 oz
(112 g): 210 kcal, fat 13 g (sat 6, trans 1, poly 0.5, mono 5), cholesterol 75 mg, sodium 55 mg,
carbs 0, fiber 0, sugars 0, protein 22 g; vitamin D 0.4 mcg, calcium 10 mg, iron 2.1 mg,
potassium 320 mg.

What the owner did: dropped the photo, Sort with AI (local), renamed the card "Costco Lean Lamb",
Saved. The local card he got is in files/food/lamb-label-2026-11-17/drop_local.md: it was named
"Safe Handling Instructions" (a heading on the label), and the gaps were filled from USDA BEEF.

This test does the same drop with no text, local and with Redo with cloud, and saves the card
the way the app's Save does (frontend/lib/entries.ts -> POST /logs/ingredients).

How it's judged (owner, 2026-11-17: labels "seemed fine"; "why beef ... very important"):
- an ingredient is proposed from the label (source "label") with the label's numbers exactly,
  per 112 g: 210 kcal, 22 g protein, 13 g fat, 0 carbs, 0 fiber;
- the nutrients the label doesn't print are filled from a USDA LAMB food, never beef (fixed
  2026-11-17: a label that names its meat only matches that meat);
- Save puts it in his ingredient library with the label's numbers, its note under
  Personal Development/Physical/Nutrition/Ingredients.
Things seen but NOT expectations he set (kept in TESTING-LOG only): the local card's name
("Safe Handling Instructions"), vitamin D, poly/mono fat from USDA.

Sandbox: a copy of the owner's real store with his saved "Costco Lean Lamb" taken out (file, row,
index), so the drop isn't handed the answer. Run one provider per pytest call:
    cd core && .venv/bin/python -m pytest tests/user/food/test_t05_lamb_label_ingredient.py -q                      # local
    cd core && QUINTACLE_USER_PROVIDER=cloud .venv/bin/python -m pytest tests/user/food/test_t05_lamb_label_ingredient.py -q  # Claude via Max
"""
from __future__ import annotations

import os
import shutil
import sqlite3
from pathlib import Path

import pytest

from tests.claude.harness import REAL_STORE, drop, first, make_client, missing_max, missing_requirements, sandbox_before, types

PHOTO = Path(__file__).parents[1] / "files" / "food" / "lamb-label-2026-11-17" / "13455__2.jpg"
PROVIDER = os.environ.get("QUINTACLE_USER_PROVIDER", "local")
OWNER_NAME = "Costco Lean Lamb"
INGREDIENTS_FOLDER = "personal-development/physical/nutrition/ingredients"
LABEL = {"basis_amount_g": 112, "kcal": 210, "protein_g": 22, "fat_g": 13, "carbs_g": 0, "fiber_g": 0}


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    reason = missing_max() if PROVIDER == "cloud" else missing_requirements()
    if reason:
        pytest.skip(reason)
    # His data as it was when he dropped the photo (2026-11-17, before the 16:16 save): no lamb
    # or yogurt saved, no chats from 16:14 on.
    return sandbox_before(tmp_path_factory.mktemp("t05"), chats_from="2026-11-17-1614",
                          leave_out_ingredients=(OWNER_NAME, "Kirkland Signature Plain Nonfat Greek Yogurt (2/3 cup)"), cloud=PROVIDER == "cloud")


@pytest.fixture(scope="module")
def card(client):
    return first(drop(client, path=PHOTO, provider=PROVIDER), "ingredient_preset")



def test_an_ingredient_is_proposed_from_the_label(client, card):
    assert card.get("source") == "label", card.get("source")


def test_label_macros_exactly(card):
    got = {k: float(card.get(k) or 0) for k in LABEL}
    assert got == {k: float(v) for k, v in LABEL.items()}, got


def test_gaps_filled_from_usda_lamb_not_beef(card):
    desc = (card.get("usda_description") or "").lower()
    assert "lamb" in desc and "beef" not in desc, card.get("usda_description")


# ------------------------------------------------------------------ after Save


@pytest.fixture(scope="module")
def saved(client, card):
    """The card's Save (frontend/lib/entries.ts createIngredient)."""
    body = {k: card.get(k) for k in ("basis_amount_g", "protein_g", "carbs_g", "fat_g", "fiber_g", "kcal", "micros")}
    # He renamed the card "Costco Lean Lamb" before Save.
    body |= {"name": OWNER_NAME, "source": card.get("source") or "", "fdc_id": card.get("fdc_id")}
    r = client.post("/logs/ingredients", json=body)
    assert r.status_code == 200, r.text[:400]
    return r.json()


def test_saved_in_the_library_with_the_label_numbers(client, saved, card):
    rows = client.get("/logs/ingredients").json()
    row = next((r for r in rows if r["name"] == OWNER_NAME), None)
    assert row, [r["name"] for r in rows]
    assert float(row["kcal"]) == 210 and float(row["protein_g"]) == 22 and float(row["basis_amount_g"]) == 112, row


def test_saved_note_under_nutrition_ingredients(saved, card):
    import quintacle_core.api as api_module

    folder = Path(api_module.DATA_DIR) / "kb" / INGREDIENTS_FOLDER
    notes = [p.name for p in folder.glob("*.md")] if folder.exists() else []
    from quintacle_core.markdown_paths import slugify

    assert f"{slugify(OWNER_NAME)}.md" in notes, notes
