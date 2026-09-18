from __future__ import annotations

import re
from datetime import date
from typing import Annotated, Literal, Union

import anthropic
from pydantic import BaseModel, Field
from pydantic.json_schema import SkipJsonSchema

from ...llm_config import DEFAULT_MODEL

ACTIVITY_CATEGORIES = ("productivity", "social", "leisure", "yourself", "emotional")

# The Finance page's fixed tabs — distinct from FinanceEntry.category, which
# stays a freeform merchant-type guess ("groceries", "transport") for detail
# within a tab. kind is the coarse bucket the page groups by.
FINANCE_KINDS = ("subscription", "food", "alcohol", "experience", "shopping", "big_purchase", "regular")

_SYSTEM_PROMPT = """You turn a free-form journal dump into structured log entries for a \
personal tracker. Split the text into one entry per distinct thing that happened, and classify \
each one by its exact type:

- "activity": general life stuff that isn't food/exercise/a substance. Category is one of:
  - productivity: work AND personal tasks/chores that take effort (both count as productivity)
  - social: time with friends, family, or dates
  - leisure: passive/fun consumption — scrolling, books, movies, gaming, hobbies for fun
  - yourself: physical self-care and home upkeep — gym, organizing the house, everyday errands
  - emotional: how you felt, emotional processing, reflections on mood
- "food": something eaten or drunk (non-alcoholic). A known meal-preset library is provided
  below — if what's described is basically one of those presets, set meal_id to its id and
  leave estimated_kcal at 0 (the preset's real macros will be used, not a guess). Only
  estimate_kcal yourself when nothing in the library matches.
- "exercise": a specific workout/lift/sport session. Break it into individual sets:
  - Strength (weighted or bodyweight): one set entry per set, with reps and weight (weight
    null for bodyweight work like pull-ups). "3x8 @ 135lb" is 3 set entries, each reps=8,
    weight=135. "8-5-4-4" pull-ups is 4 set entries with reps 8, 5, 4, 4 and weight null.
    Also estimate total calories burned for the whole exercise (typical resistance-training
    energy expenditure — roughly 5-10 kcal per working set for a compound lift, scaled for
    load/exertion) and put that single total on the *first* set's calories_burned only,
    leaving it null on the rest — this feeds daily energy balance, and putting it on every
    set would double-count.
  - Cardio (running, swimming, cycling, etc.): one set entry for the whole session, with
    duration_min and distance filled in, reps/weight left null. Estimate calories_burned
    from the activity/duration/distance if not stated — never leave it at 0 unless truly
    undeterminable.
  Never leave calories_burned at 0/null for an exercise entry unless truly undeterminable —
  it feeds daily energy balance (kcal in vs out). IMPORTANT: if the text states an actual
  measured value (a watch/fitness tracker reading, "burned 420kcal per my watch") use that
  EXACT number instead of your own estimate — a real measurement always overrides a guess.
  A known routine library may be provided below — if the text says you did a known routine
  (by name or a paraphrase, not necessarily an exact match) rather than describing specific
  sets, return one exercise entry per exercise in that routine (using its exact names), each
  with an empty sets list — the user fills in their own reps/weight, don't invent numbers.
- "substance": alcohol or other tracked substances, with an amount.
- "todo": something to do on a specific day — a task, deadline, or event ("hackathon", "dentist
  appointment"), not something that already happened. Resolve relative/shorthand dates
  ("sept 15", "next friday") to an absolute YYYY-MM-DD using the reference date given below.
  If a time or time range is given ("1115 to 530", "at 3pm"), resolve it to 24-hour "HH:MM"
  in start_time/end_time — use context to judge am/pm/overnight when it's ambiguous; this is
  always shown for review before it's saved, so a reasonable guess is fine.
  Leave start_time/end_time null if no time was given, and due_date null if no day was given.
- "body_stat": a measured body metric — weight, body fat %, etc. metric is a short lowercase
  name ("weight"), value is the number, unit is what it's measured in ("lb", "kg", "%").
- "finance": money spent — a purchase, bill, subscription charge. amount is a positive number
  (dollars), merchant is who it was paid to if mentioned, category is a short lowercase guess
  ("groceries", "dining", "subscription", "transport") when inferable, else "".
- "kb_entry": everything else — something worth remembering that isn't a log of something that
  happened (a fact, a preference, an idea, a reference note, an object description). folder is
  a short "/"-nested KB path guess (e.g. "Organisation/Ideas"), title is a short name for the
  note, content is the note body in markdown, expanding on what was said.

Only use what's actually in the text — don't invent entries that weren't mentioned. \
Estimate hours/amounts reasonably from context; use 0 if genuinely undeterminable."""


class ActivityEntry(BaseModel):
    type: Literal["activity"]
    category: Literal["productivity", "social", "leisure", "yourself", "emotional"]
    description: str
    hours: float
    entry_date: SkipJsonSchema[str | None] = None  # filled by _resolve_entry_dates(), not by this call


class FoodEntry(BaseModel):
    type: Literal["food"]
    meal_type: Literal["breakfast", "lunch", "dinner", "snack"]
    description: str
    meal_id: int | None = None
    estimated_kcal: float
    entry_date: SkipJsonSchema[str | None] = None


class ExerciseSetRecord(BaseModel):
    reps: int | None = None
    weight: float | None = None
    weight_unit: str = "lb"
    duration_min: float | None = None
    distance: float | None = None
    distance_unit: str = "mi"
    calories_burned: float | None = None


class ExerciseEntry(BaseModel):
    type: Literal["exercise"]
    exercise_name: str
    sets: list[ExerciseSetRecord]
    notes: str = ""
    entry_date: SkipJsonSchema[str | None] = None


class SubstanceEntry(BaseModel):
    type: Literal["substance"]
    substance: str
    amount: float
    notes: str = ""
    entry_date: SkipJsonSchema[str | None] = None


class TodoEntry(BaseModel):
    type: Literal["todo"]
    title: str
    due_date: str | None = None  # YYYY-MM-DD, resolved from relative/shorthand text
    start_time: str | None = None  # "HH:MM", 24-hour
    end_time: str | None = None
    priority: int = 2  # 1=low, 2=medium, 3=high, 4=urgent


class BodyStatEntry(BaseModel):
    type: Literal["body_stat"]
    metric: str
    value: float
    unit: str = ""
    entry_date: SkipJsonSchema[str | None] = None


class FinanceEntry(BaseModel):
    type: Literal["finance"]
    amount: float
    merchant: str = ""
    category: str = ""
    notes: str = ""
    entry_date: SkipJsonSchema[str | None] = None
    # Resolved by _resolve_finance_kinds() in a small second pass, same
    # SkipJsonSchema-then-fill-in trick as entry_date above — keeps this off
    # the already-near-the-limit main union schema.
    kind: SkipJsonSchema[str] = "regular"


class KBEntryProposal(BaseModel):
    type: Literal["kb_entry"]
    folder: str
    title: str
    content: str


ParsedEntry = Annotated[
    Union[
        ActivityEntry,
        FoodEntry,
        ExerciseEntry,
        SubstanceEntry,
        TodoEntry,
        BodyStatEntry,
        FinanceEntry,
        KBEntryProposal,
    ],
    Field(discriminator="type"),
]


class ParsedJournal(BaseModel):
    entries: list[ParsedEntry]


def _format_meal_library(known_meals: list[dict]) -> str:
    if not known_meals:
        return "Known meal presets: (none saved yet)"
    lines = [f"id={m['id']} name={m['name']!r} kcal={m['kcal']}" for m in known_meals]
    return "Known meal presets:\n" + "\n".join(lines)


def _format_routine_library(known_routines: list[dict]) -> str:
    if not known_routines:
        return "Known workout routines: (none saved yet)"
    lines = [f"name={r['name']!r} exercises={r['exercises']}" for r in known_routines]
    return "Known workout routines:\n" + "\n".join(lines)


# Deterministic, local, no API call — same principle as normalize.py's
# canonicalize_name: only pay for the (cheap, but not free) second pass below
# when the text plausibly mentions a day other than today at all. An
# ordinary same-day dump ("worked out, had a burrito") never touches this.
_DATE_SIGNAL_RE = re.compile(
    r"\b(yesterday|tomorrow|last\s+\w+|next\s+\w+|\d{1,2}\s*/\s*\d{1,2}|\d{1,2}\s*-\s*\d{1,2}|"
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|"
    r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?|"
    r"mon(?:day)?|tue(?:sday)?|wed(?:nesday)?|thu(?:rsday)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?|"
    r"\d+\s+days?\s+ago|\d+\s+weeks?\s+ago|\bago\b)",
    re.IGNORECASE,
)


class _DateResolution(BaseModel):
    index: int
    entry_date: str  # YYYY-MM-DD


class _DateResolutions(BaseModel):
    resolutions: list[_DateResolution]


_DATE_RESOLVE_SYSTEM_PROMPT = (
    "You're given a journal/dump's original text, plus a numbered list of things that were "
    "already extracted from it. For each numbered item, if the ORIGINAL text states or clearly "
    "implies a date for that specific item OTHER than the reference date below (e.g. \"last "
    "Tuesday\", \"on August 3rd\", \"yesterday\", a date established earlier in the same text), "
    "resolve it to an absolute YYYY-MM-DD and include it in resolutions. If an item happened on "
    "the reference date itself, or no date is stated/implied for it, OMIT it entirely from "
    "resolutions — don't guess a date that isn't actually there."
)


def _entry_label(entry: BaseModel) -> str:
    for field in ("description", "exercise_name", "substance", "merchant", "metric"):
        value = getattr(entry, field, None)
        if value:
            return str(value)
    return ""


def _resolve_entry_dates(raw_text: str, entries: list, reference_date: date) -> None:
    """Second, deliberately tiny pass that mutates `entries` in place. Why
    this is separate from the main classification call above: ParsedJournal's
    schema is already right at Anthropic's structured-output grammar-size
    ceiling — verified live (a real 400 "compiled grammar is too large"
    error) that adding a plain entry_date field to more than 3 of its 6
    dated branches breaks it outright. entry_date is SkipJsonSchema on those
    models instead (invisible to — and so free for — the main call's schema,
    but still a real attribute afterward), and resolved here in a schema
    small enough to never come close to that limit."""
    dateable = [(i, e) for i, e in enumerate(entries) if hasattr(e, "entry_date")]
    if not dateable:
        return
    lines = [f"{i}: {e.type} — {_entry_label(e)}" for i, e in dateable]
    client = anthropic.Anthropic()
    response = client.messages.parse(
        model=DEFAULT_MODEL,
        max_tokens=2048,
        system=(
            _DATE_RESOLVE_SYSTEM_PROMPT
            + f"\n\nReference date: {reference_date.isoformat()} ({reference_date.strftime('%A')})"
        ),
        messages=[
            {
                "role": "user",
                "content": f"Original text:\n{raw_text}\n\nExtracted items:\n" + "\n".join(lines),
            }
        ],
        output_format=_DateResolutions,
    )
    by_index = {r.index: r.entry_date for r in response.parsed_output.resolutions}
    for i, entry in dateable:
        if i in by_index:
            entry.entry_date = by_index[i]


class _FinanceKindResolution(BaseModel):
    index: int
    kind: Literal["subscription", "food", "alcohol", "experience", "shopping", "big_purchase", "regular"]


class _FinanceKindResolutions(BaseModel):
    resolutions: list[_FinanceKindResolution]


_FINANCE_KIND_SYSTEM_PROMPT = (
    "For each numbered expense below, classify it into exactly one kind:\n"
    "- subscription: a recurring bill/membership/service charge (streaming, gym membership, "
    "software, phone plan)\n"
    "- food: a meal or non-alcoholic food/drink purchase (restaurant, cafe, groceries)\n"
    "- alcohol: a drink/bar tab/bottle purchase\n"
    "- experience: paying to do something — an activity, ticket, tour, entrance fee\n"
    "- shopping: clothing, gear, everyday retail items\n"
    "- big_purchase: a large one-off purchase — furniture, electronics, a major appliance\n"
    "- regular: anything else (rent, utilities, transport, general bills)\n"
    "Return one resolution per numbered item."
)


def _resolve_finance_kinds(entries: list) -> None:
    """Mirrors _resolve_entry_dates' shape exactly (separate small call,
    mutates in place) but for FinanceEntry.kind instead of entry_date."""
    finance_entries = [(i, e) for i, e in enumerate(entries) if getattr(e, "type", None) == "finance"]
    if not finance_entries:
        return
    lines = [f"{i}: merchant={e.merchant!r} category={e.category!r} amount={e.amount} notes={e.notes!r}" for i, e in finance_entries]
    client = anthropic.Anthropic()
    response = client.messages.parse(
        model=DEFAULT_MODEL,
        max_tokens=2048,
        system=_FINANCE_KIND_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": "\n".join(lines)}],
        output_format=_FinanceKindResolutions,
    )
    by_index = {r.index: r.kind for r in response.parsed_output.resolutions}
    for i, entry in finance_entries:
        if i in by_index:
            entry.kind = by_index[i]


def parse_journal_dump(
    raw_text: str,
    known_meals: list[dict] | None = None,
    reference_date: date | None = None,
    forced_type: str | None = None,
    known_routines: list[dict] | None = None,
) -> list[
    ActivityEntry
    | FoodEntry
    | ExerciseEntry
    | SubstanceEntry
    | TodoEntry
    | BodyStatEntry
    | FinanceEntry
    | KBEntryProposal
]:
    client = anthropic.Anthropic()
    ref = reference_date or date.today()
    system = (
        _SYSTEM_PROMPT
        + f"\n\nReference date (resolve relative/shorthand dates against this): {ref.isoformat()} ({ref.strftime('%A')})"
        + "\n\n"
        + _format_meal_library(known_meals or [])
        + "\n\n"
        + _format_routine_library(known_routines or [])
    )
    if forced_type is not None:
        # The TYPE has already been decided deterministically (e.g. a "food:"
        # prefix) — AI is only needed to extract the fields, not to classify.
        system += (
            f"\n\nThe user has already told us this text describes exactly one entry of type "
            f"'{forced_type}' — return exactly one entry of that type, extracting every "
            f"relevant field from the text."
        )
    response = client.messages.parse(
        model=DEFAULT_MODEL,
        max_tokens=16000,
        system=system,
        messages=[{"role": "user", "content": raw_text}],
        output_format=ParsedJournal,
    )
    entries = response.parsed_output.entries
    if _DATE_SIGNAL_RE.search(raw_text):
        _resolve_entry_dates(raw_text, entries, ref)
    _resolve_finance_kinds(entries)
    return entries
