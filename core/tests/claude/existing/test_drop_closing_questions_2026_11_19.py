"""Owner-approved fix 7, 2026-11-19: a chat answer pasted into Drop loses
its closing words to the owner ("Would you like to record this plan to your
notes?") before classification, so they stop becoming junk KB notes
("Recipe Recording Request"). Deterministic, no model."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from quintacle_core.drop_fixups import strip_chat_closing

FILES = Path(__file__).resolve().parents[2] / "user" / "files"


def _answers(rel: str) -> list[str]:
    body = (FILES / rel).read_text(encoding="utf-8")
    body = re.sub(r"^---\n.*?\n---\n", "", body, flags=re.S)
    parts = re.split(r"^### (You|Assistant)\s*$", body, flags=re.M)
    return [parts[i + 1].strip() for i in range(1, len(parts) - 1, 2) if parts[i] == "Assistant"]


def _removed(text: str) -> str:
    out = strip_chat_closing(text)
    assert text.startswith(out), "only the end may be cut"
    return text[len(out):].strip()


PAD = "Day 1: walk the High Line, lunch at Chelsea Market, then the Whitney.\n" * 6


# --- real pasted answers (tests/user/files) ---------------------------------

LAMB = "food/lamb-burger-recipe-2026-11-18/chat.md"


def test_lamb_final_answer_drops_the_bun_question_and_record_offer():
    last = _answers(LAMB)[-1]
    gone = _removed(last)
    assert gone.startswith("I still need one answer")
    assert gone.endswith("Do you want me to record this recipe to your notes?")
    assert strip_chat_closing(last).rstrip().endswith("- Cumin, if it's not in your spice rack")
    assert "| Costco Lean Lamb | 230 g" in strip_chat_closing(last)


def test_lamb_first_answer_drops_record_plan_question():
    assert _removed(_answers(LAMB)[0]) == "Would you like to record this plan to your notes for future reference?"


def test_lamb_question_and_tracking_paragraphs_go_table_stays():
    ans = _answers(LAMB)[3]
    gone = _removed(ans)
    assert gone.startswith("**Question:** is the 300 kcal per bun or for the pair?")
    assert "If you want this tracked" in gone
    kept = strip_chat_closing(ans)
    assert "| Protein | 45.2 g |" in kept and kept.endswith("This burger version swaps the rice for buns.")


def test_lamb_trailing_tracking_list_item_and_question_go_notes_stay():
    ans = _answers(LAMB)[4]
    gone = _removed(ans)
    assert gone.startswith("3. **Tracking**:") and gone.endswith("for future reference?")
    assert "Fry or scramble eggs in the lamb fat" in strip_chat_closing(ans)


def test_lamb_record_this_item_and_adjust_question_go():
    gone = _removed(_answers(LAMB)[1])
    assert gone.startswith("- **Record This**: Would you like to save this recipe")
    assert gone.endswith("(e.g., pickles, avocado)?")


@pytest.mark.parametrize("rel,idx,first_removed", [
    ("food/breakfast-2026-11-18/chat.md", 0, "Would you like to log this meal"),
    ("food/breakfast-2026-11-18/chat.md", 1, "Since this is your usual breakfast"),
    ("food/breakfast-chat-2026-11-17/chat.md", 1, "If you tell me which of these"),
    ("food/meal-plan-2026-11-17/chat.md", 1, "Nothing from this chat is saved automatically."),
    ("food/meal-plan-2026-11-17/chat.md", 2, "Would you like this saved to your notes"),
    ("food/meal-plan-2026-11-17/chat.md", 3, "Want me to multiply this"),
    ("travel/nyc-2028/chat-local-2026-11-13.md", 0, "Would you like adjustments"),
    ("travel/nyc-2028/chat-local-then-claude-2026-11-13.md", 1, "Do you want me to Record this"),
])
def test_real_answers_lose_only_their_closing(rel, idx, first_removed):
    ans = _answers(rel)[idx]
    gone = _removed(ans)
    assert gone.startswith(first_removed)
    assert len(gone) <= 0.4 * len(ans)


def test_every_real_answer_keeps_at_least_60_percent():
    for rel in [LAMB, "food/breakfast-2026-11-18/chat.md", "food/breakfast-chat-2026-11-17/chat.md",
                "food/meal-plan-2026-11-17/chat.md", "travel/nyc-2028/chat-local-then-claude-2026-11-13.md"]:
        for ans in _answers(rel):
            assert len(strip_chat_closing(ans)) >= 0.6 * len(ans)


def test_nyc_booking_section_list_is_kept():
    kept = strip_chat_closing(_answers("travel/nyc-2028/chat-local-then-claude-2026-11-13.md")[1])
    assert kept.endswith("- **Broadway and Top of the Rock:** a few weeks out is fine.")


# --- guards -----------------------------------------------------------------

def test_text_without_closing_is_returned_identical():
    text = PAD + "\nIf you use lamb instead of chicken, protein lands around 190 g."
    assert strip_chat_closing(text) == text


def test_question_in_the_middle_is_kept():
    text = "Would you like a hotel list? Here it is.\n\n" + PAD
    assert strip_chat_closing(text) == text


def test_trailing_rules_and_blank_lines_go_with_the_closing():
    text = PAD + "\n---\n\nWould you like me to save this to your notes? 🥗\n\n---\n\n"
    assert strip_chat_closing(text) == PAD.rstrip()


def test_trailing_data_list_is_never_cut():
    text = PAD + "\n**Ingredients**\n- 230 g lamb\n- 2 eggs\n- 70 g salmon"
    assert strip_chat_closing(text) == text


def test_trailing_table_is_never_cut():
    text = PAD + "\n| Nutrient | Amount |\n|---|---|\n| Protein | 45 g |"
    assert strip_chat_closing(text) == text


def test_short_typed_drop_with_own_question_is_untouched():
    text = "Ran 5k this morning, legs sore after.\n\nShould I rest tomorrow?"
    assert strip_chat_closing(text) == text


def test_all_closing_text_comes_back_unchanged():
    text = "Would you like me to record this? " * 15
    assert strip_chat_closing(text) == text


def test_more_than_40_percent_closing_comes_back_unchanged():
    text = "Lamb burger: 230 g lamb, 2 eggs, 2 buns, smashed thin.\n\n" + \
        ("Would you like to save this to your notes? I can also log it for you. " * 5)
    assert strip_chat_closing(text) == text


def test_i_cant_statement_is_content_not_an_offer():
    text = PAD + "\nI can't give you real booking IDs. Book Amtrak about 11 months ahead."
    assert strip_chat_closing(text) == text


def test_empty_and_none_like_input():
    assert strip_chat_closing("") == ""
    assert strip_chat_closing("   ") == "   "
