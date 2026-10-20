"""Text → habit/budget-line parse for the drop lane (next-wave-plan §8:
"budget:"/"habit:"/"goal:" prefixes set goals from drop or chat — "eating out
$200/month" parses into the habit shape, review-gated, committed through the
same POST /logs/habits the Dashboard form uses)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from ...llm_dispatch import parse_structured


class HabitEstimate(BaseModel):
    """Mirrors logs/api.py's HabitCreate body — the estimate is reviewed and
    committed straight to POST /logs/habits (upsert by name, so the same drop
    both creates a new goal and updates an existing one)."""

    name: str
    target_amount: float = 0
    target_period: Literal["day", "week", "2weeks", "month"] = "week"
    metric: Literal["activity_hours", "food_kcal", "spend", "exercise_days"] = "activity_hours"
    direction: Literal["at_least", "at_most"] = "at_least"
    unit: str = ""
    match_category: str | None = None
    match_kind: str | None = None


# The shapes below are EXACTLY what the habits page's submit() produces (its
# three goal types) plus the exercise_days count metric — the quota engine
# keys off these metric/direction/unit/matcher combinations, so a freelance
# combination would silently track nothing.
_SYSTEM_PROMPT = (
    "Structure this goal/habit/budget into one tracked habit line. Fields: name (a short label, "
    "e.g. \"Gym time\" or \"Eating out budget\"), target_amount (the number), target_period (day, "
    "week, 2weeks, or month — default week), metric, direction, unit, match_category, match_kind. "
    "Pick EXACTLY one of these shapes:\n"
    "- Time goal (\"10 hrs of productivity a week\"): metric=activity_hours, direction=at_least, "
    "unit=\"hrs\", match_category = exactly one activity category (productivity, social, leisure, "
    "yourself, emotional), match_kind=null.\n"
    "- Calorie cap (\"under 2000 kcal a day\"): metric=food_kcal, direction=at_most, unit=\"kcal\", "
    "match_category=null, match_kind=null.\n"
    "- Budget line (\"$200/month on eating out\"): metric=spend, direction=at_most, unit=\"$\", "
    "match_kind = one expense kind (subscription, food, alcohol, experience, shopping, "
    "big_purchase, regular) when one clearly fits, else null; match_category = comma-separated "
    "whole-word match terms over merchant/category/notes (e.g. \"restaurant, takeout\") when "
    "specific merchants/categories are named, else null. Both null = a cap on TOTAL spend.\n"
    "- Session count (\"gym 4x/week\"): metric=exercise_days, direction=at_least, "
    "unit=\"sessions\", match_category=null, match_kind=null.\n"
    "target_amount is always the plain number (200 for \"$200\", 4 for \"4x\")."
)


def structure_habit(description: str, provider: str | None = None) -> HabitEstimate:
    """For the explicit "habit:"/"goal:"/"budget:" prefix — intent already
    stated, so no relevance gate, always extracts fields."""
    return parse_structured(_SYSTEM_PROMPT, description, HabitEstimate, provider=provider, max_tokens=1024).parsed
