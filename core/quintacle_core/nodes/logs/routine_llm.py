from __future__ import annotations

import anthropic
from pydantic import BaseModel

from ...llm_config import DEFAULT_MODEL
from ..journal.normalize import canonicalize_name

# Mirrors suggest_outfit/suggest_grooming_routine's shape, but simpler: an
# exercise "library" is just the flat set of names already logged against
# (exercise_sets), not items with their own category/description to create —
# a genuinely new exercise name is still fine to include as-is, it becomes
# part of the library the first time it's logged against.
_COMPOSER_SYSTEM_PROMPT = """You help assemble a workout routine from a real exercise-name library. \
Given a description of what's wanted and the known exercise names, list the exercises IN ORDER — \
match names to the library where it's clearly the same thing (paraphrasing is fine, e.g. "pull \
ups" -> the library's "Weighted Pull-ups"). For anything not in the library, still include it as a \
new exercise name exactly as described. Also propose name, a short name for the routine \
(e.g. "Pull Day", "Push Day", "Leg Day")."""


class WorkoutRoutineSuggestion(BaseModel):
    name: str
    exercises: list[str]


def suggest_workout_routine(description: str, known_exercise_names: list[str]) -> WorkoutRoutineSuggestion:
    client = anthropic.Anthropic()
    library = (
        "Known exercise names:\n" + "\n".join(known_exercise_names)
        if known_exercise_names
        else "Known exercise names: (none logged yet)"
    )
    response = client.messages.parse(
        model=DEFAULT_MODEL,
        max_tokens=2048,
        system=_COMPOSER_SYSTEM_PROMPT + "\n\n" + library,
        messages=[{"role": "user", "content": description}],
        output_format=WorkoutRoutineSuggestion,
    )
    return response.parsed_output


def resolve_workout_routine(suggestion: WorkoutRoutineSuggestion, known_exercise_names: list[str]) -> dict:
    """Deterministic pass, not AI — same fuzzy-match-against-the-real-library
    pattern as meal/outfit/grooming composition, so a slightly-paraphrased
    exercise name reuses the existing one instead of forking a near-duplicate."""
    return {
        "name": suggestion.name,
        "exercises": [canonicalize_name(e, known_exercise_names) for e in suggestion.exercises],
    }
