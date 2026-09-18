from __future__ import annotations

import re
from collections import Counter
from typing import Literal

from pydantic import BaseModel

Layout = Literal["list", "gallery", "cards", "table"]

# Never useful as a table column / badge on their own.
_SKIP_KEYS = {"name", "title", "type", "notes", "description"}
_MAX_COLUMNS = 4
_MAX_BADGES = 2
_MAX_BADGE_CARDINALITY = 8


class ViewConfig(BaseModel):
    layout: Layout = "list"
    columns: list[str] = []
    badges: list[str] = []
    sort_by: str | None = None
    sort_dir: Literal["asc", "desc"] = "asc"


_DATE_LIKE = re.compile(r"^\d{4}-\d{2}-\d{2}")


def _badge_ok(key: str, values: set[str]) -> bool:
    """A badge is a short categorical label (category, status, kind...) —
    not a date, not a free number, not something unique per entry."""
    if key == "date" or key.endswith("_date"):
        return False
    return not any(_DATE_LIKE.match(v) for v in values) and not all(re.fullmatch(r"-?\d+(\.\d+)?", v) for v in values)


def _scalar(v) -> bool:
    return v is not None and not isinstance(v, (list, dict))


def infer_view(rows: list[dict]) -> ViewConfig:
    """A folder's default look, worked out from what's actually in it — this
    is what lets a brand-new category need no code: photos -> gallery, several
    plain fields per entry -> table, otherwise a plain list. A saved
    _view.json always wins over this."""
    if not rows:
        return ViewConfig()

    key_counts: Counter[str] = Counter()
    values_by_key: dict[str, set] = {}
    for r in rows:
        for k, v in r["meta"].items():
            if k in _SKIP_KEYS or not _scalar(v):
                continue
            key_counts[k] += 1
            values_by_key.setdefault(k, set()).add(str(v))

    # Keys most entries share, most common first.
    common = [k for k, n in key_counts.most_common() if n >= max(1, len(rows) // 2)]
    badges = [
        k
        for k in common
        if _badge_ok(k, values_by_key[k])
        and len(values_by_key[k]) <= _MAX_BADGE_CARDINALITY
        and len(values_by_key[k]) < max(2, len(rows))
    ][:_MAX_BADGES]
    sort_by = "date" if "date" in key_counts else None

    with_assets = sum(1 for r in rows if r["assets"])
    if with_assets * 2 >= len(rows):
        return ViewConfig(layout="gallery", badges=badges)
    if len(common) >= 3:
        return ViewConfig(
            layout="table",
            columns=common[:_MAX_COLUMNS],
            sort_by=sort_by,
            sort_dir="desc" if sort_by else "asc",
        )
    if badges:
        return ViewConfig(layout="cards", badges=badges)
    return ViewConfig()
