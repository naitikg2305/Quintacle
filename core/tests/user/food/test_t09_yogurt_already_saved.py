"""T9 (TESTING-LOG.md): the owner drops his Greek yogurt label photo AGAIN, with that yogurt already
saved (T6, "Kirkland Signature Plain Nonfat Greek Yogurt (2/3 cup)"), and presses Sort with AI
(local, 2026-11-18 08:50). Feature: a saved look-alike is flagged, like travel notes (owner:
"similar to travel").

His card (files/food/greek-yogurt-again-2026-11-18/card_local.png; owner: "make this a test"):
- "Same USDA food as your saved: Kirkland Signature Plain Nonfat Greek Yogurt (2/3 cup)";
- Update "Kirkland ..." chosen by default (Save as new offered);
- per 170 g: protein 18, carbs 7, fat 0, fiber 0, kcal 100, source label;
- gaps from USDA "Yogurt, Greek, plain, nonfat".

The photo: the T6 photo, files/food/greek-yogurt-label-2026-11-17/greek_yogurt_label.jpg.
Sandbox: his data as it was at 08:50 that day (the yogurt saved). One provider per pytest call:
    cd core && .venv/bin/python -m pytest tests/user/food/test_t09_yogurt_already_saved.py -q                      # local
    cd core && QUINTACLE_USER_PROVIDER=cloud .venv/bin/python -m pytest tests/user/food/test_t09_yogurt_already_saved.py -q  # Claude via Max
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.claude.harness import drop, first, missing_max, missing_requirements, sandbox_before

PHOTO = Path(__file__).parents[1] / "files" / "food" / "greek-yogurt-label-2026-11-17" / "greek_yogurt_label.jpg"
PROVIDER = os.environ.get("QUINTACLE_USER_PROVIDER", "local")
SAVED = "Kirkland Signature Plain Nonfat Greek Yogurt (2/3 cup)"
LABEL = {"basis_amount_g": 170, "kcal": 100, "protein_g": 18, "carbs_g": 7, "fat_g": 0, "fiber_g": 0}


@pytest.fixture(scope="module")
def card(tmp_path_factory):
    reason = missing_max() if PROVIDER == "cloud" else missing_requirements()
    if reason:
        pytest.skip(reason)
    c = sandbox_before(tmp_path_factory.mktemp("t09"), chats_from="2026-11-18-0850", cloud=PROVIDER == "cloud")
    assert SAVED in [i["name"] for i in c.get("/logs/ingredients").json()], "the T6 yogurt must be saved for this test"
    return first(drop(c, path=PHOTO, provider=PROVIDER), "ingredient_preset")


def test_flags_his_saved_yogurt(card):
    assert (card.get("existing_match") or {}).get("name") == SAVED, card.get("existing_match")


def test_update_is_the_default_choice(card):
    assert card.get("on_conflict") == "update", card.get("on_conflict")


def test_read_from_the_label_exactly(card):
    assert card.get("source") == "label", card.get("source")
    got = {k: float(card.get(k) or 0) for k in LABEL}
    assert got == {k: float(v) for k, v in LABEL.items()}, got


def test_gaps_from_usda_plain_nonfat_greek_yogurt(card):
    desc = (card.get("usda_description") or "").lower()
    assert all(w in desc for w in ("yogurt", "greek", "plain", "nonfat")), card.get("usda_description")
