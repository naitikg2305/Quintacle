from __future__ import annotations

import re
from pathlib import Path

import frontmatter


def safe_metadata(post: "frontmatter.Post", stem: str, defaults: dict | None = None) -> dict:
    """A structured store's folder (Fitness/routines, Style & Dressing/items,
    etc.) isn't exclusively written by that store's own write() — a
    folder-scoped KB chat can push a plain note into the exact same folder,
    producing a file with none of the fields the store expects. Reading it
    with a bare `.metadata["name"]` then crashes the WHOLE list endpoint over
    one stray file (this happened for real: a routine discussed in chat and
    pushed as a generic note broke every /drop call). Falls back to the
    filename for `name` and merges in whatever `defaults` the caller needs,
    so a malformed file degrades to "one oddly-empty entry" instead of a
    500 that takes the rest of the store down with it."""
    metadata = post.metadata
    return {
        **(defaults or {}),
        **metadata,
        "name": metadata.get("name") or stem.replace("-", " ").title(),
    }


def slugify(text: str) -> str:
    """Lowercase, hyphenated, alnum-only — also the path-traversal guard for
    any folder/filename segment built from AI output or user input."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "entry"


def resolve_nested(root: Path, folder: str) -> Path:
    """A '/'-separated folder path (e.g. "Personal Development/Physical/Fitness")
    becomes a real nested directory, each segment slugified independently so
    the join can never escape root."""
    segments = [slugify(s) for s in folder.split("/") if s.strip()]
    return root.joinpath(*segments) if segments else root


def list_folder_tree(root: Path) -> list[str]:
    """Every folder under root, as '/'-joined relative paths, at every depth."""
    if not root.exists():
        return []
    return sorted(str(p.relative_to(root)).replace("\\", "/") for p in root.rglob("*") if p.is_dir())
