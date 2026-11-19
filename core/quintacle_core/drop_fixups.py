"""Code-decided fixes to a drop's kb_entry proposal (2026-11-13, owner
testing T1). The model suggests; these make the parts that must be right
deterministic before the review card shows them.

- planned_folder_with_year: a trip plan's folder carries the trip's year
  ("Fun/Travel/Planned/Europe" -> "Fun/Travel/Planned/Europe 2027"). The
  year comes from the plan's dates (trip_photos.parse_body_dates), else a
  year in the title. The owner can still edit it on the card.
- existing_links_only: the `links` the model proposes are kept only when
  they name a note, journal day or experience that exists ("About Travel"
  was suggested with no such note).
- trip_folder_links: a note going into a Planned trip folder links to the
  notes already in that folder -- the same trip (owner, T3 2026-11-13: the
  local model left a flight ticket unlinked from its trip's itinerary).
"""
from __future__ import annotations

import re

from .markdown_paths import slugify
from .place_graph import is_planned_folder

_YEAR_RE = re.compile(r"\b(20\d\d)\b")


NUTRITION_HOME = "Personal Development/Physical/Nutrition"
_NUTRITION_WORDS = re.compile(r"nutrition|meal|diet|food|recipe|macro", re.IGNORECASE)


def nutrition_note_folder(folder: str, existing_folders) -> str:
    """2026-11-17 (owner, T4): a meal-plan / nutrition note the model files under a NEW top
    folder ("Nutrition/Meal_Plans", "Health/Nutrition") goes to his existing Nutrition folder:
    Personal Development/Physical/Nutrition/Meal Plans. A folder whose top level already
    exists is the model's real choice and is kept."""
    parts = [p for p in (folder or "").split("/") if p.strip()]
    if not parts or not _NUTRITION_WORDS.search(folder):
        return folder
    tops = {slugify(f.split("/")[0]) for f in existing_folders or [] if f}
    if slugify(parts[0]) in tops:
        return folder
    return f"{NUTRITION_HOME}/Meal Plans"


def trip_folder_for_plain_planned(folder: str, title: str, content: str) -> str:
    """2026-11-17 (owner, T2): a trip plan the model left in plain Fun/Travel/Planned gets
    its trip subfolder from code, named after where the trip goes (derived places, code only):
    one city -> the city; several cities in one country -> the country; several countries
    on one continent -> the continent. planned_folder_with_year then adds the year, so
    "New York" -> "New York 2028" and Central Europe -> "Europe 2027" (an existing trip
    folder with that name is simply reused). Anything else is returned unchanged."""
    from .place_graph import derive_destinations

    parts = [p for p in (folder or "").split("/") if p.strip()]
    if "/".join(slugify(p) for p in parts) != "fun/travel/planned":
        return folder
    try:
        places = derive_destinations("fun/travel/planned", f"# {title}\n\n{content}")
    except Exception:
        return folder
    cities = [pl for pl in places if pl.city]
    if not places:
        return folder
    countries = {pl.country for pl in places if pl.country}
    continents = {pl.continent for pl in places if pl.continent}
    if len(cities) == 1 and len(countries) <= 1:
        name = cities[0].city
    elif len(countries) == 1:
        name = next(iter(countries))
    elif len(continents) == 1:
        name = next(iter(continents))
    else:
        name = (cities[0].city if cities else places[0].country) or ""
    if not name:
        return folder
    return "/".join([*parts, name])


def _plan_year(title: str, content: str) -> int | None:
    from .trip_photos import parse_body_dates

    start, _ = parse_body_dates(f"{title}\n{content}")
    if start:
        return start.year
    m = _YEAR_RE.search(title or "")
    return int(m.group(1)) if m else None


def trip_folder_matches_plan(folder: str, title: str, content: str) -> str:
    """2026-11-18 (owner, T2 fix d): when the model files a plan into an EXISTING trip folder
    (Fun/Travel/Planned/<trip>), that folder must be this trip: its year must not differ from
    the plan's year, and at least half the places the plan names must lie inside the places
    the folder names ("New York" is not inside "Europe 2027"). Otherwise the plan goes back to
    plain Planned and gets its own folder from its places (trip_folder_for_plain_planned;
    planned_folder_with_year then adds the year), exactly as a plan the model left in plain
    Planned does. A folder name that isn't a place ("Honeymoon 2027") is only checked by year."""
    from .gazetteer import find_places
    from .place_graph import _folder_mentions, _prose

    parts = [p for p in (folder or "").split("/") if p.strip()]
    slug_parts = [slugify(p) for p in parts]
    if slug_parts[:3] != ["fun", "travel", "planned"] or len(parts) < 4:
        return folder
    plain = "/".join(parts[:3])
    trip_seg = parts[3]
    m = _YEAR_RE.search(trip_seg)
    folder_year = int(m.group(1)) if m else None
    plan_year = _plan_year(title, content)
    if folder_year and plan_year and folder_year != plan_year:
        return trip_folder_for_plain_planned(plain, title, content)
    no_year = "/".join(["fun/travel/planned"] + [slugify(_YEAR_RE.sub("", p)).strip("-") for p in parts[3:]])
    try:
        folder_places = _folder_mentions(no_year)
        plan_places = find_places(_prose(f"# {title}\n\n{content}"))
    except Exception:
        return folder
    if not folder_places or not plan_places:
        return folder

    def inside(pl) -> bool:
        for fp in folder_places:
            if fp.city and pl.city == fp.city:
                return True
            if not fp.city and fp.country and pl.country == fp.country:
                return True
            if not fp.city and not fp.country and fp.continent and pl.continent == fp.continent:
                return True
        return False

    if sum(1 for pl in plan_places if inside(pl)) * 2 >= len(plan_places):
        return folder
    return trip_folder_for_plain_planned(plain, title, content)


def planned_folder_with_year(folder: str, title: str, content: str) -> str:
    from .trip_photos import parse_body_dates

    parts = [p for p in (folder or "").split("/") if p.strip()]
    slug = "/".join(slugify(p) for p in parts)
    if not is_planned_folder(slug) or len(parts) < 4:  # Fun/Travel/Planned/<trip> only
        return folder
    if _YEAR_RE.search(parts[-1]):
        return folder
    start, _ = parse_body_dates(f"{title}\n{content}")
    year = start.year if start else None
    if year is None:
        m = _YEAR_RE.search(title or "")
        year = int(m.group(1)) if m else None
    if year is None:
        return folder
    parts[-1] = f"{parts[-1]} {year}"
    return "/".join(parts)


def existing_links_only(links, known_titles) -> list[str]:
    # 2026-11-13 (owner): the same exact, case-insensitive rule typed links
    # resolve by (graph.typed_link_key) — "quintacle" keeps "Quintacle", but
    # a near-miss like "Quintacles" is dropped instead of fuzzy-snapped.
    from .graph import typed_link_key

    canonical: dict[str, str] = {}
    for k in known_titles:
        canonical.setdefault(typed_link_key(k), str(k))
    out: list[str] = []
    for link in links or []:
        name = canonical.get(typed_link_key(link)) if str(link or "").strip() else None
        if name and name not in out:
            out.append(name)
    return out


_MAX_TRIP_LINKS = 10


def trip_folder_links(store, folder: str, links) -> list[str]:
    """`links` plus the titles of the notes already in the same Planned trip
    folder (Fun/Travel/Planned/<trip>), so a ticket, booking or revised plan
    always links to the rest of its trip -- code, not the model's choice."""
    out = list(links or [])
    parts = [p for p in (folder or "").split("/") if p.strip()]
    if not is_planned_folder("/".join(slugify(p) for p in parts)) or len(parts) < 4:
        return out
    try:
        rows = store.list_entries_meta(folder)
    except Exception:
        return out
    taken = {slugify(x) for x in out}
    added = 0
    for r in rows:
        title = r.get("title") or ""
        if added >= _MAX_TRIP_LINKS or r["slug"].startswith("_") or not title or slugify(title) in taken:
            continue
        out.append(title)
        taken.add(slugify(title))
        added += 1
    return out


# --- 2026-11-19 (owner, fix 7): a pasted chat answer's closing lines ------
# A chat answer pasted into Drop ends with the assistant talking to the
# owner ("Would you like to record this plan to your notes?", "**Question:**
# is the 300 kcal per bun or for the pair? ..."). Classified as-is, those
# lines became their own junk notes ("Recipe Recording Request").
# strip_chat_closing drops them from the END only, code-decided.

_CLOSING_START = re.compile(
    r"^(?:would you like|would you prefer|do you want|want me to|shall i|should i|"
    r"let me know|just let me know|feel free|happy to|"
    r"if you(?:'d| would)? (?:want|like|prefer|tell me|let me know|confirm)|"
    r"if (?:it|that|so) does\b|once (?:you|it'?s|it is|that'?s)|i still need|"
    r"i can\s|i could\s|i'll\s|i will\s|"
    r"nothing (?:from|in|here)[^.?!]* (?:is|was|gets) saved|"
    r"question:|next step|the best next step|you could also (?:log|save|record|track)|"
    r"since this is your usual|saving it as|it'?s worth (?:logging|saving|recording)|"
    r"tracking:|track:|record this:|record:|save:|logging:)",
    re.IGNORECASE,
)
_CLOSING_ANYWHERE = re.compile(
    r"\b(?:record|save|saved|saving|log|logging|track|tracked)\b[^.?!]*\b(?:notes?|preset|quintacle)\b",
    re.IGNORECASE,
)
_CONTINUATION = re.compile(r"^(?:that way|this way|then\b|that means|otherwise|so\s)", re.IGNORECASE)
_LIST_LINE = re.compile(r"^\s*(?:[-*+]\s|\d+[.)]\s|\|)")
_TOP_ITEM = re.compile(r"^(?:[-*+]\s|\d+[.)]\s)")
_STRUCTURE_LINE = re.compile(r"^\s*(?:[-*+]\s|\d+[.)]\s|\||#|>)")
_RULE_LINE = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")
_MARKUP = re.compile(r"[*_`]+")
_EMOJI = re.compile(r"[\U0001F000-\U0001FAFF☀-➿️]")
_SENTENCE_SPLIT = re.compile(r"(?<=[.?!])\s+")
_MAX_CLOSING_SHARE = 0.4
# A pasted chat answer is long; a short typed drop ("ran 5k, legs sore.
# Should I rest tomorrow?") is the owner's own words and stays whole.
_MIN_CHAT_CHARS = 300


def _plain(s: str) -> str:
    s = _MARKUP.sub("", _EMOJI.sub("", s))
    s = re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+", "", s)
    return s.replace("’", "'").strip()


def _sentence_closing(sentence: str) -> bool:
    s = sentence.strip()
    return bool(s.endswith("?") or _CLOSING_START.match(s) or _CLOSING_ANYWHERE.search(s))


def _paragraph_closing(paragraph: str) -> bool:
    """Prose only (no list/table/heading line). Closing when its first
    sentence is, or its last is and at least half are; a "That way.../
    Then..." sentence counts like the one before it."""
    lines = paragraph.splitlines()
    if any(_STRUCTURE_LINE.match(ln) for ln in lines):
        return False
    sentences = [s for s in _SENTENCE_SPLIT.split(_plain(" ".join(ln.strip() for ln in lines))) if s.strip()]
    if not sentences:
        return False
    flags: list[bool] = []
    for s in sentences:
        flags.append(flags[-1] if (flags and _CONTINUATION.match(s)) else _sentence_closing(s))
    return flags[0] or (flags[-1] and sum(flags) * 2 >= len(flags))


def _strip_trailing_list_items(block: list[str]) -> list[str]:
    """Drop closing items ("- **Record This**: Would you like to save...",
    "3. **Tracking**: ... meal preset") from the end of a list; stops at the
    first item with real content."""
    lines = list(block)
    while lines:
        start = next((i for i in range(len(lines) - 1, -1, -1) if _TOP_ITEM.match(lines[i])), None)
        if start is None or any(_LIST_LINE.match(ln) and ln.lstrip().startswith("|") for ln in lines[start:]):
            break
        item = _plain(" ".join(ln.strip() for ln in lines[start:]))
        sentences = [s for s in _SENTENCE_SPLIT.split(item) if s.strip()]
        if not sentences or not all(_sentence_closing(s) for s in sentences):
            break
        lines = lines[:start]
    return lines


def strip_chat_closing(text: str) -> str:
    """`text` minus the assistant's trailing words to the user (questions,
    offers to record/save/log, "Once you tell me...", trailing `---` rules
    and blank lines). Works backwards from the end and stops at the first
    real content; never touches the middle, a table, or a data list. If the
    cut would empty the text or remove over 40% of it, or the text is
    shorter than a chat answer (300 chars), `text` comes back unchanged. Deterministic -- no model."""
    if not text or len(text.strip()) < _MIN_CHAT_CHARS:
        return text
    blocks = re.split(r"\n\s*\n", text.rstrip())
    changed = False
    while blocks:
        last = blocks[-1]
        if not last.strip() or all(_RULE_LINE.match(ln) or not ln.strip() for ln in last.splitlines()):
            blocks.pop()
            changed = True
            continue
        lines = last.splitlines()
        # a trailing `---` under a block counts as part of the closing
        while lines and (_RULE_LINE.match(lines[-1]) or not lines[-1].strip()):
            lines.pop()
            changed = True
        if _paragraph_closing("\n".join(lines)):
            blocks.pop()
            changed = True
            continue
        kept = _strip_trailing_list_items(lines)
        if len(kept) < len(lines):
            changed = True
            if kept and any(ln.strip() for ln in kept):
                blocks[-1] = "\n".join(kept)
                continue
            blocks.pop()
            continue
        blocks[-1] = "\n".join(lines)
        break
    if not changed:
        return text
    out = "\n\n".join(blocks).rstrip()
    if not out.strip() or len(text.strip()) - len(out.strip()) > _MAX_CLOSING_SHARE * len(text.strip()):
        return text
    return out
