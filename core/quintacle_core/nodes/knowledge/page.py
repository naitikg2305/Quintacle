"""The Knowledge page (2026-11-05) — a website-style index over the KB's
`Knowledge/**` tree, modelled on the PersonalWebsite's /knowledge page.

Everything is derived at request time from the files on disk, never from a
hard-coded list: a new subfolder under Knowledge/ is a new topic chip the
next time the page loads, a new `tags:` value is a new tag chip. Pure code,
no model calls (deterministic core).

- Topics = the folder tree under knowledge/ (assets/ and `_`-dirs skipped),
  each with a subtree note count and, when the folder has an `about-*`
  charter note, that charter's first paragraph as its description.
- Tags = frontmatter `tags` / `category` (top-level or inside `fields`),
  grouped case-insensitively, plus graph-linked place/project hubs (one SQL
  query over the edges table).
- Notes = every non-charter .md under knowledge/, newest `edited` first.

This is an OWNER surface, not a model surface: private notes are listed
(flagged `private`, the UI shows a lock) — nothing here feeds a prompt.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import frontmatter

from ... import clock
from ..kb.privacy import is_private_meta, note_node_id, note_parts
from ..kb.store import KBStore, _ASSET_LINES_RE, _frontmatter_assets, _title_of

ROOT = "knowledge"
SUMMARY_CHARS = 240
_HUB_PREFIXES = (("note:places/", "place"), ("place:", "place"), ("note:projects/", "project"))


def _is_charter(slug: str) -> bool:
    return slug.startswith("about-")


def _skip_dir(name: str) -> bool:
    return name == "assets" or name.startswith("_") or name.startswith(".")


def humanize(segment: str) -> str:
    return segment.replace("-", " ").replace("_", " ").strip().title() or segment


def topic_label(topic: str) -> str:
    """`tech-notes/graphs` -> "Tech Notes › Graphs" ("" for the root)."""
    return " › ".join(humanize(s) for s in topic.split("/") if s)


def first_paragraph(body: str, limit: int = SUMMARY_CHARS) -> str:
    """First meaningful paragraph of a markdown body: headings, asset lines,
    HTML comments, code fences, tables, rules and images are skipped; the
    paragraph's lines are joined and lightly de-markdowned."""
    para: list[str] = []
    in_fence = False
    for raw in (body or "").splitlines():
        line = raw.strip()
        if line.startswith("```") or line.startswith("~~~"):
            in_fence = not in_fence
            if para:
                break
            continue
        if in_fence:
            continue
        if not line:
            if para:
                break
            continue
        if (
            line.startswith("#")
            or line.startswith("<!--")
            or line.startswith("|")
            or line.startswith("![")
            or _ASSET_LINES_RE.match(line)
            or re.fullmatch(r"[-*_]{3,}", line)
            or line.endswith("<!-- place -->")
            or line.endswith("<!-- filemeta -->")
        ):
            if para:
                break
            continue
        para.append(re.sub(r"^([-*+]|\d+\.)\s+", "", line).lstrip("> "))
    text = " ".join(para)
    text = re.sub(r"\[\[([^\]]+)\]\]", r"\1", text)  # [[wiki]] -> wiki
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)  # [label](url) -> label
    text = re.sub(r"(\*\*|__|\*|`)([^*`]+?)\1", r"\2", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        text = text[: limit - 1].rsplit(" ", 1)[0].rstrip(",;:—-") + "…"
    return text


def _body_without_title(content: str) -> str:
    stripped = content.lstrip()
    if stripped.startswith("#"):
        parts = stripped.split("\n", 1)
        return parts[1] if len(parts) > 1 else ""
    return content


def _as_list(value) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(v).strip() for v in value if str(v).strip()]
    return [s.strip().lstrip("#") for s in str(value).split(",") if s.strip()]


def note_tags(meta: dict) -> list[str]:
    """`tags` / `category` from top-level frontmatter or `fields`, de-duped
    case-insensitively, first spelling wins."""
    fields = meta.get("fields") if isinstance(meta.get("fields"), dict) else {}
    out: list[str] = []
    seen: set[str] = set()
    for source in (meta, fields):
        for key in ("tags", "category", "categories"):
            for tag in _as_list(source.get(key)):
                if tag.lower() not in seen:
                    seen.add(tag.lower())
                    out.append(tag)
    return out


def _edited(meta: dict, path: Path) -> str:
    stamp = meta.get("edited")
    if isinstance(stamp, datetime):
        return stamp.isoformat(timespec="seconds")
    if stamp:
        return str(stamp)
    # Hand-dropped files never went through KBStore.write — fall back to the
    # file's mtime, in Eastern Time like every other stamp.
    return datetime.fromtimestamp(path.stat().st_mtime, clock.TIME_ZONE).isoformat(timespec="seconds")


def _retrieval_summary(node_id: str, title: str) -> str:
    try:
        from ...retrieval import get_retrieval_index

        row = get_retrieval_index().get_node(node_id)
    except Exception:
        return ""
    summary = ((row or {}).get("summary") or "").strip()
    return "" if summary == title.strip() else summary


def _index_title(node_id: str) -> str:
    try:
        from ...retrieval import get_retrieval_index

        row = get_retrieval_index().get_node(node_id)
    except Exception:
        return ""
    return (row or {}).get("title") or ""


def _hub_label(other: str) -> tuple[str, str] | None:
    for prefix, kind in _HUB_PREFIXES:
        if other.startswith(prefix):
            rest = other[len(prefix):]
            if prefix.startswith("note:"):
                return humanize(rest.split("/", 1)[0]), kind  # the hub = its top folder
            return _index_title(other) or humanize(rest.rsplit("/", 1)[-1]), kind
    return None


def _hub_tags(note_ids: set[str]) -> dict[str, list[tuple[str, str]]]:
    """node id -> [(label, kind)] of graph-linked place/project hubs, from ONE
    query over the edges table. No graph store wired -> {}."""
    try:
        from ...graph import get_graph_store

        rows = get_graph_store().conn.execute(
            "SELECT source_id, target_id FROM edges WHERE source_id LIKE 'note:knowledge/%' OR target_id LIKE 'note:knowledge/%'"
        ).fetchall()
    except Exception:
        return {}
    labels: dict[str, tuple[str, str] | None] = {}
    out: dict[str, list[tuple[str, str]]] = {}
    for row in rows:
        for mine, other in ((row["source_id"], row["target_id"]), (row["target_id"], row["source_id"])):
            if mine not in note_ids:
                continue
            if other not in labels:
                labels[other] = _hub_label(other)
            pair = labels[other]
            if pair and pair not in out.setdefault(mine, []):
                out[mine].append(pair)
    return out


def _dirs(root: Path) -> list[Path]:
    """root + every dir under it, minus assets/ and `_`/`.` dirs (at any depth)."""
    found = [
        p for p in root.rglob("*")
        if p.is_dir() and not any(_skip_dir(part) for part in p.relative_to(root).parts)
    ]
    return [root, *sorted(found)]


def _topic_of(root: Path, d: Path) -> str:
    return "/".join(d.relative_to(root).parts)


def build_index(kb: KBStore) -> dict:
    """{topics, tags, notes, root_count, charter} for the whole Knowledge
    tree — see the module docstring. Notes still carry a private `_body`
    (stripped before the response) for the substring search lane."""
    root = kb.root / ROOT
    if not root.is_dir():
        return {"topics": [], "tags": [], "notes": [], "root_count": 0, "charter": ""}

    notes: list[dict] = []
    charters: dict[str, str] = {}
    dirs = _dirs(root)
    for d in dirs:
        topic = _topic_of(root, d)
        folder = f"{ROOT}/{topic}" if topic else ROOT
        for md in sorted(d.glob("*.md")):
            slug = md.stem
            if slug.startswith("_"):
                continue
            try:
                post = frontmatter.loads(md.read_text(encoding="utf-8"))
            except Exception:
                continue  # one malformed file never takes the page down
            meta = dict(post.metadata)
            fields = meta.get("fields") if isinstance(meta.get("fields"), dict) else {}
            body = _body_without_title(post.content)
            if _is_charter(slug):
                if topic not in charters:
                    charters[topic] = str(meta.get("summary") or fields.get("summary") or "").strip() or first_paragraph(body)
                continue
            title = _title_of(post, slug)
            node_id = note_node_id(folder, slug)
            summary = str(meta.get("summary") or fields.get("summary") or "").strip()
            summary = summary or _retrieval_summary(node_id, title) or first_paragraph(body)
            notes.append(
                {
                    "id": node_id,
                    "folder": folder,
                    "slug": slug,
                    "title": title,
                    "topic": topic,
                    "topic_label": topic_label(topic),
                    "tags": note_tags(meta),
                    "hubs": [],
                    "summary": summary,
                    "edited": _edited(meta, md),
                    "has_assets": bool(
                        _frontmatter_assets(meta) or _ASSET_LINES_RE.search(post.content) or "](assets/" in post.content
                    ),
                    "private": is_private_meta(meta),
                    "_body": post.content,
                }
            )

    hubs = _hub_tags({n["id"] for n in notes})
    for n in notes:
        n["hubs"] = [{"label": label, "kind": kind} for label, kind in hubs.get(n["id"], [])]

    # Topic tree with subtree counts.
    direct: dict[str, int] = {}
    for n in notes:
        direct[n["topic"]] = direct.get(n["topic"], 0) + 1
    nodes: dict[str, dict] = {}
    for d in dirs[1:]:
        topic = _topic_of(root, d)
        nodes[topic] = {
            "topic": topic,
            "name": humanize(topic.rsplit("/", 1)[-1]),
            "label": topic_label(topic),
            "folder": f"{ROOT}/{topic}",
            "count": sum(c for t, c in direct.items() if t == topic or t.startswith(topic + "/")),
            "direct_count": direct.get(topic, 0),
            "description": charters.get(topic, ""),
            "children": [],
        }
    topics: list[dict] = []
    for topic in sorted(nodes):
        parent = topic.rsplit("/", 1)[0] if "/" in topic else None
        (nodes[parent]["children"] if parent in nodes else topics).append(nodes[topic])

    # Tags: frontmatter tags + hub links, grouped case-insensitively.
    tag_rows: dict[str, dict] = {}
    for n in notes:
        for tag in n["tags"]:
            row = tag_rows.setdefault(f"tag:{tag.lower()}", {"tag": tag, "count": 0, "kind": "tag"})
            row["count"] += 1
        for hub in n["hubs"]:
            row = tag_rows.setdefault(f"{hub['kind']}:{hub['label'].lower()}", {"tag": hub["label"], "count": 0, "kind": hub["kind"]})
            row["count"] += 1
    tags = sorted(tag_rows.values(), key=lambda r: (-r["count"], r["kind"] != "tag", r["tag"].lower()))

    notes.sort(key=lambda n: n["title"].lower())
    notes.sort(key=lambda n: n["edited"], reverse=True)
    return {"topics": topics, "tags": tags, "notes": notes, "root_count": direct.get("", 0), "charter": charters.get("", "")}


def _search_ids(q: str, notes: list[dict]) -> list[str]:
    """Ranked note ids matching `q`: the shared retrieval index (FTS5 +
    vectors, RRF) restricted to knowledge notes first, then a plain
    case-insensitive substring pass over title/tags/body for anything the
    index hasn't seen (hand-dropped files, a fresh install)."""
    ids = {n["id"] for n in notes}
    ranked: list[str] = []
    try:
        from ...retrieval import retrieve

        for hit in retrieve(q, k=100):
            if hit["id"] in ids and hit["id"] not in ranked:
                ranked.append(hit["id"])
    except Exception:
        pass
    needle = q.strip().lower()
    for n in notes:
        if n["id"] in ranked:
            continue
        hay = " ".join([n["title"], n["summary"], " ".join(n["tags"]), n["_body"]]).lower()
        if needle and needle in hay:
            ranked.append(n["id"])
    return ranked


def knowledge_page(kb: KBStore, q: str | None = None, topic: str | None = None, tag: str | None = None) -> dict:
    """GET /knowledge. topics/tags always describe the WHOLE tree (so the
    filter bar never shrinks under its own filter); `notes` is filtered."""
    data = build_index(kb)
    notes = data["notes"]
    data["total"] = len(notes)
    if topic:
        t = topic.strip("/").lower()
        if t == ROOT:
            t = ""
        elif t.startswith(ROOT + "/"):
            t = t[len(ROOT) + 1 :]
        notes = [n for n in notes if not t or n["topic"] == t or n["topic"].startswith(t + "/")]
    if tag:
        want = tag.strip().lower()
        notes = [
            n for n in notes
            if want in {x.lower() for x in n["tags"]} or want in {h["label"].lower() for h in n["hubs"]}
        ]
    if q and q.strip():
        order = {nid: i for i, nid in enumerate(_search_ids(q, notes))}
        notes = sorted((n for n in notes if n["id"] in order), key=lambda n: order[n["id"]])
    data["notes"] = [{k: v for k, v in n.items() if k != "_body"} for n in notes]
    return data


def knowledge_note(kb: KBStore, folder: str, slug: str) -> dict | None:
    """One note for the reading view: KBStore.read_full + topic + private +
    related notes from 1-hop graph neighbors (note ids resolved to
    folder/slug so the UI can link them)."""
    full = kb.read_full(folder, slug)
    if full is None:
        return None
    meta = kb.read_meta(folder, slug) or {}
    topic = folder[len(ROOT) + 1 :] if folder.startswith(ROOT + "/") else ""
    node_id = note_node_id(folder, slug)
    related: list[dict] = []
    try:
        from ...retrieval import neighbor_labels

        for nb in neighbor_labels(node_id):
            parts = note_parts(nb["id"])
            related.append(
                {
                    "id": nb["id"],
                    "title": nb["title"],
                    "edge_type": nb["edge_type"],
                    "folder": parts[0] if parts else None,
                    "slug": parts[1] if parts else None,
                    "knowledge": bool(parts and (parts[0] == ROOT or parts[0].startswith(ROOT + "/"))),
                }
            )
    except Exception:
        related = []
    path = kb.entry_path(folder, slug)
    return {
        **full,
        "id": node_id,
        "topic": topic,
        "topic_label": topic_label(topic),
        "tags": note_tags(meta),
        "edited": _edited(meta, path),
        "private": is_private_meta(meta),
        "related": related,
    }
