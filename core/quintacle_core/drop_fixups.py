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
"""
from __future__ import annotations

import re

from .markdown_paths import slugify
from .place_graph import is_planned_folder

_YEAR_RE = re.compile(r"\b(20\d\d)\b")


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
