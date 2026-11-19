"""T6 (TESTING-LOG.md): the owner drops a photo of his Kirkland plain nonfat Greek yogurt label,
local and with Redo with cloud, to compare the two (2026-11-17).

The label (2/3 cup = 170 g): 100 kcal, fat 0 (sat 0, trans 0), cholesterol 10 mg, sodium 65 mg,
carbs 7 g (fiber 0, sugars 4 g, added 0 g), protein 18 g; vit D 0 mcg, calcium 220 mg, iron 0 mg,
potassium 270 mg. Nothing else is printed.

His two cards are in files/food/greek-yogurt-label-2026-11-17/ (drop_local.md, drop_claude.md):
- local: right macros; took potassium from USDA (240) instead of the label (270); no added sugars.
- Claude: right macros, potassium 270; but tagged 22 nutrients "label" that are NOT on the label
  (vitamin A, B vitamins, zinc, iodine, chloride...), and took sugars from USDA (5.56, label 4).

How it's judged (owner, 2026-11-17: labels "seemed fine"; the USDA match must be the right food):
- an ingredient is proposed from the label (source "label") with the label's numbers exactly,
  per 170 g: 100 kcal, 18 g protein, 7 g carbs, 0 fat, 0 fiber;
- gaps are filled from USDA Greek plain nonfat yogurt, not plain yogurt (fixed 2026-11-17: a name
  match whose protein is off by more than max(3 g, 30%) loses to the label's own numbers).
Things seen but NOT expectations he set (TESTING-LOG only): potassium/added sugars missed by local;
Claude tagging nutrients "label" that aren't printed; serving size in Claude's name.

The photo: files/food/greek-yogurt-label-2026-11-17/greek_yogurt_label.jpg (copied from the owner's
Desktop testing folder, Food recipe/20260908_203808.jpg). Sandbox: a copy of the owner's real store. One provider per pytest call:
    cd core && .venv/bin/python -m pytest tests/user/food/test_t06_greek_yogurt_label.py -q                      # local
    cd core && QUINTACLE_USER_PROVIDER=cloud .venv/bin/python -m pytest tests/user/food/test_t06_greek_yogurt_label.py -q  # Claude via Max
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from tests.claude.harness import REAL_STORE, drop, first, make_client, missing_max, missing_requirements, sandbox_before

FILES = Path(__file__).parents[1] / "files" / "food" / "greek-yogurt-label-2026-11-17"
PHOTO = FILES / "greek_yogurt_label.jpg"
PROVIDER = os.environ.get("QUINTACLE_USER_PROVIDER", "local")
LABEL = {"basis_amount_g": 170, "kcal": 100, "protein_g": 18, "carbs_g": 7, "fat_g": 0, "fiber_g": 0}


@pytest.fixture(scope="module")
def card(tmp_path_factory):
    reason = missing_max() if PROVIDER == "cloud" else missing_requirements()
    if reason:
        pytest.skip(reason)
    if not PHOTO.exists():
        pytest.skip(f"put the owner's yogurt label photo at {PHOTO}")
    # His data as it was when he dropped the photo (2026-11-17, before the 16:21 save): the lamb
    # was saved, the yogurt wasn't; no chats from 16:18 on.
    c = sandbox_before(tmp_path_factory.mktemp("t06"), chats_from="2026-11-17-1618",
                       leave_out_ingredients=("Kirkland Signature Plain Nonfat Greek Yogurt (2/3 cup)",), cloud=PROVIDER == "cloud")
    return first(drop(c, path=PHOTO, provider=PROVIDER), "ingredient_preset")



def test_read_from_the_label(card):
    assert card.get("source") == "label", card.get("source")


def test_label_macros_exactly(card):
    got = {k: float(card.get(k) or 0) for k in LABEL}
    assert got == {k: float(v) for k, v in LABEL.items()}, got


def test_gaps_from_usda_plain_nonfat_greek_yogurt(card):
    desc = (card.get("usda_description") or "").lower()
    assert all(w in desc for w in ("yogurt", "greek", "plain", "nonfat")), card.get("usda_description")
