"""Build B — "Update website": Quintacle knowledge notes and approved
record entries -> PersonalWebsite markdown, committed onto a NEW local git
branch (never pushed, never merged, the owner's checkout never touched).

Deterministic everywhere except one advisory step (rank_candidates: the
local model flags which candidates look like website material, with a
one-line reason — the owner approves/rejects each). Privacy and the alias
table are code, never model-decided:

- private notes are never candidates, never sent to the ranker, never
  rendered (re-checked at generate time);
- only `public: true`, non-private hubs (hubs.py) may appear on the site,
  renamed to their `public_name`; a knowledge note mentioning a NON-public
  hub is blocked, an entry bullet mentioning one is dropped.

Website formats targeted (from ~/code/PersonalWebsite/frontend/src/lib):
  knowledge/<slug>.md                 frontmatter title, category, slug, summary
  projects/{Software,Featured}/<slug>/index.md
                                      title, category: software, order, date,
                                      tags, summary, github (+ markdown body)
  employment/<slug>.md                title, order, company, dates, location,
                                      slug, summaryPoints, positions[].bullets
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

import frontmatter
from pydantic import BaseModel, Field

from ... import clock
from ...graph import title_mentioned
from ...llm_dispatch import parse_structured
from ...markdown_paths import slugify
from ..kb.privacy import is_private_meta
from ..logs.worklog import WORKLOG_KIND
from .hubs import HUB_ROOTS, Hub, is_hub_location
from .record import ParsedRecord, entry_bullets

# Folder prefixes (slugified paths) that never feed the website: daily
# logs/journal, Me, people, finance/admin (Organisation), health & body,
# dating, travel diary, stocks, emergent places, and anything vault-adjacent.
# Extend with QUINTACLE_WEBSITE_EXCLUDE="a/b,c".
EXCLUDED_PREFIXES = (
    "daily-log",
    "journal",
    "me",
    "people",
    "places",
    "organisation",
    "finance",
    "vault",
    "stocks-investments",
    "personal-development/health",
    "personal-development/mind",
    "personal-development/physical/grooming",
    "personal-development/physical/style-dressing",
    "fun/dates",
    "fun/travel",
)
_EXCLUDED_SEGMENTS = {"logs", "presets", "assets", "transactions"}
MAX_CANDIDATES = 40
RANK_BATCH = 10

_ASSET_LINE_RE = re.compile(r"^\[asset\]\([^)]*\)\s*$", re.MULTILINE)
_WIKI_RE = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
_APP_LINK_RE = re.compile(r"\[([^\]]+)\]\((?:/kb/|/documents/|/wardrobe/|/grooming/|/home/)[^)]*\)")
_MANAGED_START = "<!-- quintacle:highlights:start -->"
_MANAGED_END = "<!-- quintacle:highlights:end -->"


class WebsiteRepoError(Exception):
    """The website repo can't be written (missing, not git, dirty tree)."""


# --- time stamps -----------------------------------------------------------


def parse_stamp(raw) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        dt = raw
    else:
        try:
            dt = datetime.fromisoformat(str(raw))
        except ValueError:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=clock.TIME_ZONE)


def note_edited(kb, folder: str, slug: str, meta: dict) -> str:
    """`edited` (stamped by every KBStore.write) — the real last-edit time.
    Notes written before stamping existed fall back to the file's mtime,
    never to the retrieval index's updated_at (a reindex resets that)."""
    stamp = parse_stamp(meta.get("edited"))
    if stamp is None:
        stamp = datetime.fromtimestamp(kb.entry_path(folder, slug).stat().st_mtime, clock.TIME_ZONE)
    return stamp.isoformat(timespec="seconds")


# --- exclusion + aliasing ---------------------------------------------------


def excluded_prefixes() -> tuple[str, ...]:
    extra = [slugify_path(p) for p in os.environ.get("QUINTACLE_WEBSITE_EXCLUDE", "").split(",") if p.strip()]
    return EXCLUDED_PREFIXES + tuple(extra)


def slugify_path(path: str) -> str:
    return "/".join(slugify(p) for p in path.split("/") if p.strip())


def _under(folder: str, prefix: str) -> bool:
    return folder == prefix or folder.startswith(prefix + "/")


def owning_hub(folder: str, hubs: list[Hub]) -> Hub | None:
    """`projects/quintacle/design` -> the Projects/Quintacle hub (folder-hub
    pattern or same-slug root hub)."""
    parts = folder.split("/")
    if len(parts) < 2 or parts[0] not in HUB_ROOTS:
        return None
    for h in hubs:
        if h.kind == parts[0] and h.slug == parts[1]:
            return h
    return None


def alias_text(text: str, hubs: list[Hub]) -> tuple[str, list[str], list[dict]]:
    """(text with public hubs renamed to public_name, NON-public hub titles
    mentioned -> blocked, renames applied). Never model-decided."""
    blocked, renames = [], []
    for h in hubs:
        if not (h.public and not h.private) and title_mentioned(h.title, text):
            blocked.append(h.title)
    for h in hubs:
        if h.public and not h.private and h.public_name != h.title and title_mentioned(h.title, text):
            guard = "\x00PUBLICNAME\x00"
            text = re.sub(re.escape(h.public_name), guard, text)
            text = re.sub(r"\b" + re.escape(h.title) + r"\b", h.public_name, text, flags=re.IGNORECASE)
            text = text.replace(guard, h.public_name)
            renames.append({"from": h.title, "to": h.public_name})
    return text, sorted(set(blocked)), renames


def _public_body(content: str) -> str:
    content = _ASSET_LINE_RE.sub("", content)
    content = _WIKI_RE.sub(lambda m: m.group(2) or m.group(1), content)
    content = _APP_LINK_RE.sub(r"\1", content)
    return re.sub(r"\n{3,}", "\n\n", content).strip() + "\n"


def default_summary(content: str) -> str:
    for para in re.split(r"\n\s*\n", content):
        para = para.strip()
        if not para or para.startswith(("#", "[asset]", "|", "```", "-", "*")):
            continue
        sentence = re.split(r"(?<=[.!?])\s+", " ".join(para.split()), maxsplit=1)[0]
        return sentence[:240]
    return ""


def default_category(folder: str) -> str:
    last = folder.split("/")[-1]
    return last.replace("-", " ").title() if last else "Other"


# --- candidates -------------------------------------------------------------


def knowledge_candidates(kb, hubs: list[Hub], state: dict, record_location: tuple[str, str] | None) -> tuple[list[dict], int]:
    """Notes edited after the website watermark that may be website
    material: not private, not in an excluded area, not a hub, not a log /
    structured row, not the record note, not a remembered rejection (unless
    edited since). Oldest first, capped — the rest wait for the next run."""
    watermark = parse_stamp(state.get("watermark"))
    rejected = state.get("rejected") or {}
    prefixes = excluded_prefixes()
    out = []
    for folder in kb.list_folders():
        if any(_under(folder, p) for p in prefixes):
            continue
        if set(folder.split("/")) & _EXCLUDED_SEGMENTS:
            continue
        for slug in kb.list_entries(folder):
            if record_location and (folder, slug) == record_location:
                continue
            if is_hub_location(folder, slug):
                continue
            if folder.split("/")[0] in HUB_ROOTS:
                hub = owning_hub(folder, hubs)
                if hub is None or not hub.public or hub.private:
                    continue  # company/project docs follow their hub's public flag
            meta = kb.read_meta(folder, slug) or {}
            if is_private_meta(meta) or meta.get("type") or (meta.get("fields") or {}).get("kind") == WORKLOG_KIND:
                continue
            edited = note_edited(kb, folder, slug, meta)
            if watermark is not None and parse_stamp(edited) <= watermark:
                continue
            node_id = f"note:{folder}/{slug}"
            if rejected.get(node_id) == edited:
                continue
            content = kb.read(folder, slug) or ""
            lines = content.split("\n")
            title = lines[0].lstrip("# ").strip() if lines and lines[0].startswith("#") else slug
            body = "\n".join(lines[1:]) if lines and lines[0].startswith("#") else content
            _, blocked, renames = alias_text(content, hubs)
            out.append(
                {
                    "id": node_id,
                    "kind": "knowledge",
                    "title": title,
                    "folder": folder,
                    "slug": slug,
                    "stamp": edited,
                    "edited": edited,
                    "snippet": " ".join(body.split())[:220],
                    "target_path": f"knowledge/{slugify(title)}.md",
                    "blocked": blocked,
                    "renames": renames,
                    "category": default_category(folder),
                    "summary": default_summary(body),
                }
            )
    out.sort(key=lambda c: c["edited"])
    more = max(0, len(out) - MAX_CANDIDATES)
    return out[:MAX_CANDIDATES], more


def site_path(hub: Hub, repo: Path | None, content_dir: str) -> str:
    """Where a public hub's page lives under content/: an EXISTING file at
    the hub's public_slug or (fallback) its plain title slug wins — so
    "Projects/Quintacle" (public_name "The Quintacle") updates the site's
    existing projects/Software/quintacle/ page — else a new file at
    public_slug. Projects: Software/ then Featured/, new ones in Software/."""
    slugs = list(dict.fromkeys([hub.public_slug, slugify(hub.title)]))
    if hub.kind == "projects":
        options = [f"projects/{sub}/{s}/index.md" for s in slugs for sub in ("Software", "Featured")]
        default = f"projects/Software/{hub.public_slug}/index.md"
    else:
        options = [f"employment/{s}.md" for s in slugs]
        default = f"employment/{hub.public_slug}.md"
    if repo is not None:
        for rel in options:
            if (repo / content_dir / rel).exists():
                return rel
    return default


def entry_candidates(rec: ParsedRecord | None, hubs: list[Hub], state: dict, mapping: dict, repo: Path | None, content_dir: str) -> list[dict]:
    """Public hubs whose mapped record entry changed since the website last
    published it (entry text hash differs) and that weren't rejected at this
    exact version. `mapping` = {hub_id: entry_id} (deterministic, hubs.map_hub)."""
    if rec is None:
        return []
    hashes = state.get("entry_hashes") or {}
    rejected = state.get("rejected") or {}
    out = []
    for h in hubs:
        if not h.public or h.private:
            continue
        entry_id = mapping.get(h.id)
        entry = rec.entry(entry_id) if entry_id else None
        if entry is None:
            continue
        digest = rec.entry_hash(entry_id)
        cid = f"entry:{entry_id}"
        if hashes.get(entry_id) == digest or rejected.get(cid) == digest:
            continue
        kind = "project" if h.kind == "projects" else "employment"
        target = site_path(h, repo, content_dir)
        out.append(
            {
                "id": cid,
                "kind": kind,
                "title": f"{h.public_name} — record {entry_id} {entry.title}",
                "hub_id": h.id,
                "entry_id": entry_id,
                "stamp": digest,
                "snippet": "; ".join(b["text"] for b in entry_bullets(rec, entry_id)[:3])[:220],
                "target_path": target,
                "blocked": [],
                "renames": [],
                "suggest": True,
                "reason": "record entry changed since the last website run",
            }
        )
    return out


# --- the advisory model step ------------------------------------------------

RANK_SYSTEM = """You help a person decide which of their personal knowledge notes belong on their
public portfolio website (technical write-ups, how-tos, learnings, project notes).
Personal life admin, private matters, raw todo lists and fragments are NOT website material.
For every id given, return website true/false and a short one-line reason (max 15 words).
Return only the ids you were given."""


class RankItem(BaseModel):
    id: str
    website: bool
    reason: str = ""


class Ranking(BaseModel):
    items: list[RankItem] = Field(default_factory=list)


def rank_candidates(candidates: list[dict], provider: str | None = None) -> list[dict]:
    """Annotates knowledge candidates in place with suggest/reason. Only
    non-private notes ever get here (filtered upstream). A model failure
    degrades to suggest=None + the error, never blocks the run."""
    todo = [c for c in candidates if c["kind"] == "knowledge"]
    for i in range(0, len(todo), RANK_BATCH):
        batch = todo[i : i + RANK_BATCH]
        user = "\n\n".join(
            f"id: {c['id']}\ntitle: {c['title']}\nfolder: {c['folder']}\ntext: {c['snippet']}" for c in batch
        )
        try:
            result = parse_structured(RANK_SYSTEM, user, Ranking, provider=provider, max_tokens=1500)
            by_id = {r.id: r for r in result.parsed.items}
        except Exception as e:  # advisory only — the owner still decides
            for c in batch:
                c["suggest"], c["reason"] = None, f"AI ranking unavailable: {str(e)[:120]}"
            continue
        for c in batch:
            r = by_id.get(c["id"])
            c["suggest"] = r.website if r else None
            c["reason"] = (r.reason.strip()[:160] if r else "not ranked")
    return candidates


# --- rendering ----------------------------------------------------------------


def _dump(meta: dict, body: str) -> str:
    post = frontmatter.Post(body, **meta)
    return frontmatter.dumps(post, sort_keys=False) + "\n"


def render_knowledge(kb, folder: str, slug: str, hubs: list[Hub], *, category: str, summary: str) -> tuple[str, str]:
    """(target path under content/, file text). Raises ValueError when the
    note is private or mentions a non-public hub (re-checked here, at
    generate time, not trusted from the run)."""
    meta = kb.read_meta(folder, slug)
    if meta is None:
        raise ValueError("note no longer exists")
    if is_private_meta(meta):
        raise ValueError("note is private")
    content = kb.read(folder, slug) or ""
    text, blocked, _ = alias_text(content, hubs)
    if blocked:
        raise ValueError(f"mentions non-public hub(s): {', '.join(blocked)}")
    lines = text.split("\n")
    title = lines[0].lstrip("# ").strip() if lines and lines[0].startswith("#") else slug
    file_slug = slugify(title)
    summary_text, _, _ = alias_text(summary or "", hubs)
    fm = {"title": title, "category": category or default_category(folder), "slug": file_slug, "summary": summary_text}
    return f"knowledge/{file_slug}.md", _dump(fm, _public_body(text))


def _public_bullets(rec: ParsedRecord, entry_id: str, hubs: list[Hub], *, only_wl: bool = False) -> tuple[list[str], list[str]]:
    """Publishable bullets of an entry: no `[?]`, tags stripped, aliased;
    bullets naming a non-public hub dropped (returned second)."""
    bullets = entry_bullets(rec, entry_id)
    phrasing = [b for b in bullets if b["kind"] == "phrasing"] or [b for b in bullets if b["kind"] == "detail"]
    pool = [b for b in bullets if any("WL" in t for t in b["tags"])] if only_wl else phrasing
    keep, dropped = [], []
    for b in pool:
        if any("?" in t for t in b["tags"]):
            continue
        text, blocked, _ = alias_text(b["text"], hubs)
        (dropped if blocked else keep).append(b["text"] if blocked else text)
    return keep, dropped


def render_project(repo: Path, content_dir: str, rel: str, hub: Hub, rec: ParsedRecord, entry_id: str, hubs: list[Hub]) -> tuple[str, list[str]]:
    bullets, dropped = _public_bullets(rec, entry_id, hubs)
    block = "\n".join([_MANAGED_START, "## Highlights", "", *[f"- {b}" for b in bullets], _MANAGED_END])
    path = repo / content_dir / rel
    if path.exists():
        text = path.read_text(encoding="utf-8")
        if _MANAGED_START in text and _MANAGED_END in text:
            pre, rest = text.split(_MANAGED_START, 1)
            _, post = rest.split(_MANAGED_END, 1)
            return pre + block + post, dropped
        return text.rstrip("\n") + "\n\n" + block + "\n", dropped
    entry = rec.entry(entry_id)
    fm = {
        "title": hub.public_name,
        "category": "software",
        "order": 999,
        "date": clock.today().isoformat(),
        "tags": [t for t in entry.tech if t][:10],
        "summary": bullets[0] if bullets else "",
    }
    if hub.public_repo:
        fm["github"] = hub.public_repo
    return _dump(fm, f"# {hub.public_name}\n\n{block}\n"), dropped


def render_employment(repo: Path, content_dir: str, rel: str, hub: Hub, rec: ParsedRecord, entry_id: str, hubs: list[Hub]) -> tuple[str, list[str]]:
    path = repo / content_dir / rel
    if path.exists():
        post = frontmatter.loads(path.read_text(encoding="utf-8"))
        new, dropped = _public_bullets(rec, entry_id, hubs, only_wl=True)
        meta = dict(post.metadata)
        positions = meta.get("positions") or []
        have = set()
        for p in positions:
            for b in p.get("bullets") or []:
                have.add(b.get("main", "") if isinstance(b, dict) else str(b))
                if isinstance(b, dict):
                    have.update(b.get("sub") or [])
        have.update(meta.get("summaryPoints") or [])
        add = [b for b in new if b not in have]
        if not add:
            return path.read_text(encoding="utf-8"), dropped
        if positions:
            positions[0].setdefault("bullets", [])
            positions[0]["bullets"] = list(positions[0]["bullets"] or []) + [{"main": b} for b in add]
            meta["positions"] = positions
        else:
            meta["summaryPoints"] = list(meta.get("summaryPoints") or []) + add
        return _dump(meta, post.content), dropped
    bullets, dropped = _public_bullets(rec, entry_id, hubs)
    entry = rec.entry(entry_id)
    title = re.sub(r"^Work\s+[—-]\s+", "", entry.title).split(",")[0].strip()
    fm = {
        "title": title,
        "order": 999,
        "company": hub.public_name,
        "dates": "",
        "location": "",
        "slug": hub.public_slug,
        "summaryPoints": bullets,
    }
    return _dump(fm, ""), dropped


# --- git: a new branch, written with plumbing ----------------------------------


def _git(repo: Path, *args: str, env: dict | None = None, input_text: str | None = None) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            input=input_text,
            env={**os.environ, **(env or {})},
        )
    except FileNotFoundError as e:
        # 2026-11-05: e.g. a phone/Termux backend without `pkg install git` —
        # a readable 409, never a 500.
        raise WebsiteRepoError("git is not installed on this machine — Update website needs git and the PersonalWebsite checkout (desktop feature)") from e
    if proc.returncode != 0:
        raise WebsiteRepoError(f"git {' '.join(args[:2])} failed: {proc.stderr.strip() or proc.stdout.strip()}")
    return proc.stdout


def check_repo(repo: Path) -> None:
    """Missing / not a repo / dirty working tree -> WebsiteRepoError. A dirty
    tree aborts: the owner's uncommitted work is never stashed or discarded."""
    if not repo.is_dir():
        raise WebsiteRepoError(f"website repo not found at {repo} (set QUINTACLE_WEBSITE_REPO)")
    try:
        _git(repo, "rev-parse", "--git-dir")
    except WebsiteRepoError as e:
        if isinstance(e.__cause__, FileNotFoundError):
            raise  # git itself is missing — keep that message
        raise WebsiteRepoError(f"{repo} is not a git repository") from e
    dirty = _git(repo, "status", "--porcelain").strip()
    if dirty:
        n = len(dirty.splitlines())
        raise WebsiteRepoError(
            f"{repo} has {n} uncommitted change(s) — commit or stash them yourself, then run Generate again. Nothing was written."
        )


def _free_branch(repo: Path, base: str) -> str:
    name, n = base, 1
    while subprocess.run(["git", "-C", str(repo), "show-ref", "--verify", "--quiet", f"refs/heads/{name}"]).returncode == 0:
        n += 1
        name = f"{base}-{n}"
    return name


def write_branch(repo: Path, content_dir: str, files: dict[str, str], message: str) -> dict:
    """Commits `files` ({path under content_dir: text}) onto a NEW branch
    `quintacle/content-YYYY-MM-DD[-N]` off the current HEAD using git
    plumbing (a temporary index, hash-object, write-tree, commit-tree,
    update-ref) — the owner's working tree, index and checked-out branch are
    never touched, nothing is pushed or merged. Returns the diff summary."""
    check_repo(repo)
    base = _git(repo, "rev-parse", "HEAD").strip()
    branch = _free_branch(repo, f"quintacle/content-{clock.today().isoformat()}")
    with tempfile.TemporaryDirectory() as tmp:
        env = {"GIT_INDEX_FILE": str(Path(tmp) / "index")}
        _git(repo, "read-tree", "HEAD", env=env)
        for rel, text in sorted(files.items()):
            path = f"{content_dir}/{rel}".replace("//", "/")
            sha = _git(repo, "hash-object", "-w", "--stdin", input_text=text).strip()
            _git(repo, "update-index", "--add", "--cacheinfo", f"100644,{sha},{path}", env=env)
        tree = _git(repo, "write-tree", env=env).strip()
    if tree == _git(repo, "rev-parse", "HEAD^{tree}").strip():
        return {"branch": None, "commit": None, "base": base, "files": [], "message": "no content changes — no branch created"}
    commit = _git(repo, "commit-tree", tree, "-p", base, "-m", message).strip()
    _git(repo, "update-ref", f"refs/heads/{branch}", commit, "0" * 40)
    changed = []
    status = {line.split("\t", 1)[1]: line.split("\t", 1)[0] for line in _git(repo, "diff", "--name-status", base, commit).splitlines() if "\t" in line}
    for line in _git(repo, "diff", "--numstat", base, commit).splitlines():
        added, removed, path = line.split("\t", 2)
        changed.append({"path": path, "status": status.get(path, "M"), "added": int(added) if added.isdigit() else 0, "removed": int(removed) if removed.isdigit() else 0})
    return {"branch": branch, "commit": commit, "base": base, "files": changed}
