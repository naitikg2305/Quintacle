"""Time grounding + the Me lane for chat context (next-wave-plan §10,
2026-10-20).

Three pieces, all deterministic code — no model call anywhere in this module:

- `detect_dates(text, today)`: a pure parser that resolves date words in the
  user's question — explicit forms ("April 14", "4/14", "2026-04-14",
  "oct 7th") and relative words ("today", "yesterday", "last tuesday",
  "two weeks ago", "last week") — into real `date`s. Year inference for
  month-day forms picks the most recent PAST occurrence (asking about
  "April 14" in October means last April, not next). today comes from
  clock.today() at the call site — Eastern Time, never the host zone.

- `day_bundle(d)`: that day's full picture as finished context text —
  journal content (incl. the auto photo-journal "with <people> at <place>"
  lines), every SQLite log row for the date as its already-computed
  one-liner (retrieval.log_row_title_and_summary — numbers from SQL, never
  re-derived), todos due/completed, and the day's events + 1-hop
  people/place edge labels from the graph. Capped at ~6,000 chars,
  truncated deterministically from the last section backwards (journal
  first, connections last).

- `me_context(store)`: the always-hydrated "About the user" block — the
  curated half (every note in the KB folder `Me`, capped) plus the computed
  half, LIVE from SQL at ask-time and never stored: strength PRs (max
  logged weight per exercise), this month's income/spend/savings rate,
  latest body stat per metric — each as a finished one-liner with its as-of
  date. Empty store → sections are omitted silently; nothing at all → None.

Everything degrades gracefully: a store singleton that isn't wired in this
process (bare-store tests) just means that section is skipped — never an
error surfaced to chat. The in-app path shares assembly IDEAS with the MCP
`day_recall` tool via quintacle_core.day_bundle helpers, but never imports
MCP server machinery.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

# --- detect_dates: the pure, deterministic date-word parser -----------------

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_MONTH_RE = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)
_WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}
_WEEKDAY_RE = r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
_NUMBER_WORDS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}
_NUMBER_WORD_RE = r"(?:a|an|one|two|three|four|five|six|seven|eight|nine|ten|\d{1,2})"
_ORDINAL = r"(?:st|nd|rd|th)?"

# Each pattern yields (match, handler). Compiled once; scanned longest-match
# -first so "day before yesterday" never half-matches as "yesterday".
_ISO_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_NUMERIC_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b")
_MONTH_DAY_RE = re.compile(
    rf"\b({_MONTH_RE})\.?\s+(\d{{1,2}}){_ORDINAL}(?:,?\s+(\d{{4}}))?\b", re.IGNORECASE
)
_DAY_MONTH_RE = re.compile(
    rf"\b(\d{{1,2}}){_ORDINAL}\s+(?:of\s+)?({_MONTH_RE})(?:,?\s+(\d{{4}}))?\b", re.IGNORECASE
)
_RELATIVE_RE = re.compile(
    rf"\b(day before yesterday|yesterday|today|tonight|tomorrow"
    rf"|last week|last ({_WEEKDAY_RE})"
    rf"|({_NUMBER_WORD_RE}) (day|week)s? ago)\b",
    re.IGNORECASE,
)


def _most_recent_past(month: int, day: int, today: date) -> date | None:
    """Year inference for a month-day with no year: the most recent occurrence
    not after today. Walks back a few years so Feb 29 resolves to the last
    real leap day instead of vanishing."""
    for back in range(0, 5):
        try:
            candidate = date(today.year - back, month, day)
        except ValueError:
            continue  # e.g. Feb 29 in a non-leap year — keep walking back
        if candidate <= today:
            return candidate
    return None


def _explicit_date(month: int, day: int, year_text: str | None, today: date) -> list[date]:
    if year_text:
        year = int(year_text)
        if year < 100:
            year += 2000
        try:
            return [date(year, month, day)]
        except ValueError:
            return []
    resolved = _most_recent_past(month, day, today)
    return [resolved] if resolved else []


def _relative_dates(match: re.Match, today: date) -> list[date]:
    phrase = match.group(1).lower()
    if phrase in ("today", "tonight"):
        return [today]
    if phrase == "yesterday":
        return [today - timedelta(days=1)]
    if phrase == "day before yesterday":
        return [today - timedelta(days=2)]
    if phrase == "tomorrow":
        return [today + timedelta(days=1)]
    if phrase == "last week":
        # The previous Monday-to-Sunday week, all seven days — the caller
        # caps how many actually hydrate (chat takes the first 3).
        start = today - timedelta(days=today.weekday() + 7)
        return [start + timedelta(days=i) for i in range(7)]
    if match.group(2):  # "last <weekday>" — the most recent one strictly before today
        delta = (today.weekday() - _WEEKDAYS[match.group(2).lower()]) % 7 or 7
        return [today - timedelta(days=delta)]
    if match.group(3):  # "<N> days/weeks ago"
        word = match.group(3).lower()
        n = _NUMBER_WORDS.get(word) or int(word)
        days = n * (7 if match.group(4).lower() == "week" else 1)
        return [today - timedelta(days=days)]
    return []


def detect_dates(text: str, today: date) -> list[date]:
    """Every date the text mentions, resolved against `today` (clock.today()
    at the call site — Eastern). Pure and deterministic: regex + calendar
    arithmetic, no model. Results keep first-mention order, de-duplicated;
    invalid dates (Feb 30, month 24) are skipped silently."""
    candidates: list[tuple[int, int, list[date]]] = []  # (start, -len, dates)

    for m in _ISO_RE.finditer(text):
        try:
            candidates.append((m.start(), -len(m.group(0)), [date(int(m.group(1)), int(m.group(2)), int(m.group(3)))]))
        except ValueError:
            pass
    for m in _NUMERIC_RE.finditer(text):
        # US-style month/day — "4/14" is April 14.
        candidates.append((m.start(), -len(m.group(0)), _explicit_date(int(m.group(1)), int(m.group(2)), m.group(3), today)))
    for m in _MONTH_DAY_RE.finditer(text):
        month = _MONTHS[m.group(1).lower()[:3]]
        candidates.append((m.start(), -len(m.group(0)), _explicit_date(month, int(m.group(2)), m.group(3), today)))
    for m in _DAY_MONTH_RE.finditer(text):
        month = _MONTHS[m.group(2).lower()[:3]]
        candidates.append((m.start(), -len(m.group(0)), _explicit_date(month, int(m.group(1)), m.group(3), today)))
    for m in _RELATIVE_RE.finditer(text):
        candidates.append((m.start(), -len(m.group(0)), _relative_dates(m, today)))

    # Longest match at each position wins; overlapping shorter matches drop
    # (so "4/14/2026" never ALSO yields a year-inferred "4/14").
    candidates.sort()
    taken_until = -1
    result: list[date] = []
    for start, neg_len, dates in candidates:
        end = start + (-neg_len)
        if start < taken_until:
            continue
        taken_until = end
        for d in dates:
            if d not in result:
                result.append(d)
    return result


# --- day_bundle: one day's full record as finished context text -------------

_BUNDLE_CHAR_CAP = 6000
# Edge kinds that mean "a person or a place was part of this" — the 1-hop
# labels worth surfacing on a day's nodes (graph_capture + auto_journal mint
# these from journal mentions and photo perception).
_PEOPLE_PLACE_KINDS = {"with_person", "mentions_person", "at_location"}


def _journal_section(d: date) -> str | None:
    try:
        from ..journal.api import get_store as get_journal_store

        content = get_journal_store().load(d)
    except Exception:
        return None
    return content.strip() if content and content.strip() else None


def _day_row_ids(repo, d: date) -> list[str]:
    """Every SQLite log row for the date, as graph member ids, in a fixed
    kind order — the one-liners come from log_row_title_and_summary so the
    numbers are the already-computed ones."""
    ids: list[str] = []
    ids += [f"activity:{r['id']}" for r in repo.activities_for_date(d)]
    ids += [f"exercise:{r['id']}" for r in repo.exercise_for_date(d)]
    ids += [f"food:{r['id']}" for r in repo.food_log_for_date(d)]
    ids += [f"expense:{r['id']}" for r in repo.expenses_for_date(d)]
    ids += [f"income:{r['id']}" for r in repo.income_between(d, d)]
    ids += [f"body_stat:{r['id']}" for r in repo.body_stats_for_date(d)]
    ids += [f"substance:{r['id']}" for r in repo.substances_for_date(d)]
    return ids


def _rows_section(d: date) -> str | None:
    try:
        from ...retrieval import log_row_title_and_summary
        from ..logs.api import get_repo

        repo = get_repo()
        lines = []
        for member_id in _day_row_ids(repo, d):
            parts = log_row_title_and_summary(repo.conn, member_id)
            if parts is not None:
                lines.append(f"- {parts[1]}")
    except Exception:
        return None
    return "\n".join(lines) if lines else None


def _todos_section(d: date) -> str | None:
    try:
        from ..schedule.api import get_store as get_schedule_store

        todos = get_schedule_store().list()
    except Exception:
        return None
    lines = [f"- due: {t.title}" + (" (done)" if t.done else "") for t in todos if t.due_date == d]
    lines += [
        f"- completed: {t.title}"
        for t in sorted(
            (t for t in todos if t.done and t.completed_at and t.completed_at.date() == d),
            key=lambda t: t.completed_at,
        )
    ]
    return "\n".join(lines) if lines else None


def _connections_section(d: date) -> str | None:
    """The day's graph neighborhood: events linked to the day (pre-grouped
    member labels via day_bundle.day_events-style queries) plus 1-hop
    people/place edge labels for the journal node and every note linked to
    the day — "who was there, where it was", straight from the edges table."""
    try:
        from ...graph import get_graph_store
        from ...retrieval import neighbor_labels

        edges_conn = get_graph_store().conn
    except Exception:
        return None
    journal_id = f"journal:{d.isoformat()}"
    lines: list[str] = []
    try:
        day_node_ids = [journal_id] + sorted(
            row["source_id"]
            for row in edges_conn.execute(
                "SELECT DISTINCT source_id FROM edges WHERE target_id = ? AND kind = 'on_day'", (journal_id,)
            ).fetchall()
        )
        seen: set[tuple[str, str]] = set()
        for node_id in day_node_ids:
            for n in neighbor_labels(node_id):
                if n["edge_type"] not in _PEOPLE_PLACE_KINDS:
                    continue
                key = (n["id"], n["edge_type"])
                if key in seen:
                    continue
                seen.add(key)
                lines.append(f"- {n['title']} ({n['edge_type']}, {n['id']})")
            if node_id.startswith("event:"):
                members = sorted(
                    row["source_id"]
                    for row in edges_conn.execute(
                        "SELECT DISTINCT source_id FROM edges WHERE target_id = ? AND kind = 'part_of'", (node_id,)
                    ).fetchall()
                )
                if members:
                    lines.append(f"- {node_id}: {', '.join(members)} (same capture)")
    except Exception:
        return None
    return "\n".join(lines) if lines else None


def day_bundle(d: date) -> str:
    """The day's full picture as finished context text — all code, zero model
    calls, every number already computed in SQL. Sections in a fixed order
    (journal, log rows, todos, people/places/events); the ~6,000-char cap
    truncates deterministically from the LAST section backwards, so the
    journal narrative survives longest. Empty day → empty string (the caller
    skips the heading entirely)."""
    sections = [
        ("Journal", _journal_section(d)),
        ("Logged that day", _rows_section(d)),
        ("Todos", _todos_section(d)),
        ("People, places & events", _connections_section(d)),
    ]
    parts: list[str] = []
    total = 0
    for heading, body in sections:
        if not body:
            continue
        section = f"### {heading}\n{body}"
        if total + len(section) > _BUNDLE_CHAR_CAP:
            room = _BUNDLE_CHAR_CAP - total
            if room > len(f"### {heading}\n") + 40:  # only a truncation worth reading
                parts.append(section[:room].rstrip() + "\n(…truncated)")
            break
        parts.append(section)
        total += len(section) + 2
    return "\n\n".join(parts)


# --- me_context: the always-hydrated "About the user" block -----------------

_ME_FOLDER = "Me"
_ME_NOTES_CHAR_CAP = 3000
_PR_LIMIT = 5

# Max logged weight per exercise, straight from exercise_sets.sets_json via
# SQLite's json_each — arithmetic in SQL, the model only ever sees the
# finished number. SQLite's bare-column-with-MAX rule makes unit/reps/date
# come from the same set row that holds the max.
_PR_SQL = """
SELECT e.exercise_name AS name,
       MAX(CAST(json_extract(s.value, '$.weight') AS REAL)) AS weight,
       COALESCE(json_extract(s.value, '$.weight_unit'), 'lb') AS unit,
       json_extract(s.value, '$.reps') AS reps,
       e.date AS date
FROM exercise_sets AS e, json_each(COALESCE(e.sets_json, '[]')) AS s
WHERE json_extract(s.value, '$.weight') IS NOT NULL
GROUP BY e.exercise_name
ORDER BY weight DESC, e.exercise_name
LIMIT ?
"""

# Latest row per metric (date, then id, descending) — one finished
# "as of" fact per metric, never an average or a model guess.
_LATEST_BODY_STAT_SQL = """
SELECT b.metric, b.value, b.unit, b.date
FROM body_stats AS b
WHERE NOT EXISTS (
    SELECT 1 FROM body_stats AS b2
    WHERE b2.metric = b.metric AND (b2.date > b.date OR (b2.date = b.date AND b2.id > b.id))
)
ORDER BY b.metric
"""


def _curated_me_notes(store) -> str | None:
    """Every note in the KB folder `Me` (the §10 quick-reference self —
    injuries, preferences, people facts the user chose to write down),
    capped. Folder absent → None, silently."""
    try:
        slugs = store.list_entries(_ME_FOLDER)
    except Exception:
        return None
    parts: list[str] = []
    total = 0
    for slug in slugs:
        entry = store.read_full(_ME_FOLDER, slug)
        if entry is None or not entry["content"].strip():
            continue
        content = entry["content"].strip()
        if content.startswith("# "):  # the title rides in the section header
            content = content.partition("\n")[2].strip()
        section = f"### {entry['title']}\n{content}"
        if total + len(section) > _ME_NOTES_CHAR_CAP:
            section = section[: _ME_NOTES_CHAR_CAP - total].rstrip()
            if section:
                parts.append(section + "\n(…truncated)")
            break
        parts.append(section)
        total += len(section) + 2
    return "\n\n".join(parts) if parts else None


def _computed_me_facts() -> str | None:
    """The live half: PRs, this month's money, latest body stats — computed
    from SQL at ask-time, NEVER stored anywhere. Empty tables → sections
    omitted silently; no repo wired in this process → None."""
    try:
        from ... import clock
        from ..logs.api import get_repo

        repo = get_repo()
    except Exception:
        return None
    today = clock.today()
    blocks: list[str] = []
    try:
        prs = repo.conn.execute(_PR_SQL, (_PR_LIMIT,)).fetchall()
        if prs:
            lines = []
            for r in prs:
                reps = f" × {int(r['reps'])}" if r["reps"] is not None else ""
                lines.append(f"- {r['name']}: {r['weight']:g} {r['unit']}{reps} (as of {r['date']})")
            blocks.append("Current strength PRs (max logged weight per exercise):\n" + "\n".join(lines))
    except Exception:
        pass
    try:
        month_start = today.replace(day=1)
        income = repo.total_income_between(month_start, today)
        spend = repo.total_spend_between(month_start, today)
        if income or spend:
            line = f"- This month ({today.strftime('%Y-%m')}): income ${income:,.2f}, spend ${spend:,.2f}"
            if income > 0:
                line += f", savings rate {(income - spend) / income * 100:.0f}%"
            blocks.append("Money:\n" + line + f" (as of {today.isoformat()})")
    except Exception:
        pass
    try:
        stats = repo.conn.execute(_LATEST_BODY_STAT_SQL).fetchall()
        if stats:
            lines = [f"- {r['metric']}: {r['value']:g} {r['unit']}".rstrip() + f" (as of {r['date']})" for r in stats]
            blocks.append("Latest body stats:\n" + "\n".join(lines))
    except Exception:
        pass
    return "\n\n".join(blocks) if blocks else None


_ME_INSTRUCTION = (
    "The numbers below are computed live from the user's own records as of "
    "right now — they are current and final; use them as-is, never "
    "recalculate or re-derive them."
)


def me_context(store) -> str | None:
    """The `## About the user` block chat prepends to EVERY context: curated
    `Me` notes + live computed facts. Both halves empty → None (the heading
    never appears over nothing)."""
    curated = _curated_me_notes(store)
    computed = _computed_me_facts()
    if curated is None and computed is None:
        return None
    parts = ["## About the user", _ME_INSTRUCTION]
    if curated:
        parts.append(curated)
    if computed:
        parts.append(computed)
    return "\n\n".join(parts)
