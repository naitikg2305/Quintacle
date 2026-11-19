"""Drop save log: what every drop proposed and what the owner finally saved.

2026-11-19 (owner: "lets have a save log this way we can test better"):
testing a drop used to need screenshots of the review cards. Now every
POST /drop appends one "drop" line and every Save on the drop/scratchpad page
appends one "save" line (POST /drop-log/save), joined by `drop_id`.

Where: `<DATA_DIR>/drop-log/YYYY-MM-DD.jsonl` (Eastern date, clock.py), one
JSON object per line, append-only. DATA_DIR is the one api.py resolves
(`QUINTACLE_DATA_DIR` env, else ~/.quintacle) and hands over via `init()`.

Record format (every line has "ts" = Eastern ISO time and "kind"):

  {"ts": "2026-11-19T14:02:11.123456-05:00", "kind": "drop",
   "drop_id": "<uuid4 hex>",
   "text": "<input text as received>" | null,      # null when private
   "files": [{"name": "receipt.jpg", "size": 123456}],   # never content
   "provider_requested": null | "cloud" | "local" | "auto",
   "provider_used": "local" | "cloud" | "mixed" | null,
   "reference_date": "2026-11-19" | "",
   "keep_as_is": false, "private_skip_ai": false,
   "warnings": [...],
   "local_unavailable": "<reason>" | null,
   "entries": [ {...proposal dict as returned...} ]}

  {"ts": "...", "kind": "save", "drop_id": "<uuid4 hex>" | null,
   "provider_used": "local" | ... | null,
   "saved":   [ {...entry exactly as saved, after edits...} ],
   "deleted": [ {...cards removed before Save...} ] | null}

Hygiene: no file bytes ever; any string starting with "data:" (a data URL)
is replaced by "<data-url omitted>", any other string over 20,000 chars is
truncated with a "…[truncated N chars]" marker. PRIVACY (owner rule:
private content never leaves its lane): a private drop (private_skip_ai, or
any entry with "private": true) logs text=null and entries as
[{"type": t, "private": true}] placeholders; on a save, each private entry
becomes the same placeholder.

Logging never breaks a drop or a save: every public function catches
everything and only logs a warning.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

from . import clock

logger = logging.getLogger(__name__)

MAX_TEXT = 20_000
_lock = threading.Lock()
_data_dir: Path | None = None


def init(data_dir: Path) -> None:
    """Called from api.create_app with its DATA_DIR (so a test's monkeypatched
    DATA_DIR / QUINTACLE_DATA_DIR sandbox is honoured)."""
    global _data_dir
    _data_dir = Path(data_dir)


def log_dir() -> Path:
    base = _data_dir or Path(os.environ.get("QUINTACLE_DATA_DIR", Path.home() / ".quintacle"))
    return base / "drop-log"


def _clean(value: Any) -> Any:
    """Strip data URLs, truncate huge strings, drop bytes — recursively."""
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"<{len(value)} bytes omitted>"
    if isinstance(value, str):
        if value.startswith("data:"):
            return "<data-url omitted>"
        if len(value) > MAX_TEXT:
            return value[:MAX_TEXT] + f"…[truncated {len(value) - MAX_TEXT} chars]"
        return value
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _clean(str(value))


def _is_private(entry: Any) -> bool:
    return isinstance(entry, dict) and entry.get("private") is True


def _placeholder(entry: Any) -> dict:
    return {"type": entry.get("type") if isinstance(entry, dict) else None, "private": True}


def _entries(entries: Any, *, all_private: bool = False) -> list | None:
    if entries is None:
        return None
    if not isinstance(entries, list):
        entries = [entries]
    return [_placeholder(e) if (all_private or _is_private(e)) else _clean(e) for e in entries]


def append(kind: str, record: dict) -> None:
    """Append one JSON line (adds "ts" and "kind"). Never raises."""
    try:
        now = clock.now()
        line = {"ts": now.isoformat(), "kind": kind, **_clean(dict(record))}
        text = json.dumps(line, ensure_ascii=False, default=str)
        directory = log_dir()
        with _lock:
            directory.mkdir(parents=True, exist_ok=True)
            with open(directory / f"{now.date().isoformat()}.jsonl", "a", encoding="utf-8") as fh:
                fh.write(text + "\n")
    except Exception:
        logger.warning("drop-log: could not append a %r record", kind, exc_info=True)


def log_drop(
    *,
    drop_id: str,
    text: str | None,
    files: list[dict],
    provider_requested: str | None,
    reference_date: Any,
    keep_as_is: bool,
    private_skip_ai: bool,
    response: dict | None,
) -> None:
    """One "drop" line from /drop's inputs + the response it returned."""
    try:
        response = response or {}
        entries = response.get("entries") or []
        private = bool(private_skip_ai) or any(_is_private(e) for e in entries)
        append("drop", {
            "drop_id": drop_id,
            "text": None if private else text,
            "files": files,
            "provider_requested": provider_requested,
            "provider_used": response.get("provider_used"),
            "reference_date": "" if reference_date is None else str(reference_date),
            "keep_as_is": bool(keep_as_is),
            "private_skip_ai": bool(private_skip_ai),
            "warnings": response.get("warnings") or [],
            "local_unavailable": response.get("local_unavailable"),
            "entries": _entries(entries, all_private=private),
        })
    except Exception:
        logger.warning("drop-log: could not log a drop", exc_info=True)


def log_save(*, drop_id: str | None, saved: Any, deleted: Any, provider_used: str | None) -> None:
    """One "save" line: the entries exactly as saved (+ cards deleted first)."""
    try:
        append("save", {
            "drop_id": drop_id,
            "provider_used": provider_used,
            "saved": _entries(saved or []),
            "deleted": _entries(deleted),
        })
    except Exception:
        logger.warning("drop-log: could not log a save", exc_info=True)


def recent(limit: int = 20) -> list[dict]:
    """The last `limit` lines across the day files, newest LAST."""
    limit = max(0, int(limit))
    if limit == 0:
        return []
    directory = log_dir()
    if not directory.is_dir():
        return []
    out: list[dict] = []
    for path in sorted(directory.glob("*.jsonl"), reverse=True):  # newest day first
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for raw in reversed(lines):
            if not raw.strip():
                continue
            try:
                out.append(json.loads(raw))
            except ValueError:
                continue
            if len(out) >= limit:
                return list(reversed(out))
    return list(reversed(out))
