from __future__ import annotations

import re
from pathlib import Path

import frontmatter

from ...markdown_paths import list_folder_tree, resolve_nested, slugify

_ASSET_RE = re.compile(r"\[asset\]\(([^)]+)\)\s*$")
# Same convention, but finds every trailing [asset](...) line (a two-photo
# drop appends one per photo), not just the last — used wherever ALL of an
# entry's assets are needed, not just one representative one for the graph.
_ASSET_LINES_RE = re.compile(r"^\[asset\]\(([^)]+)\)$", re.MULTILINE)


class KBStore:
    """One markdown file per entry, grouped into nested folders (e.g.
    "Personal Development/Physical/Fitness") — the narrative/reference layer
    (recipes, technique notes, theories), distinct from the tabular data
    (meals, logs) that lives in SQLite. Folders are created on write; nothing
    here is auto-generated without a push going through it.

    Entries carry a `links` frontmatter field (AI-suggested related note
    titles, for the graph view) — kept in metadata, never in the visible
    body, so a "keep as-is" drop (an already-finished document the user
    doesn't want AI touching) still gets graph connectivity without a single
    character of its content changing. read() strips frontmatter and returns
    just the body, so every existing caller (including files written before
    this existed, with no frontmatter at all) keeps working unchanged."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def list_folders(self) -> list[str]:
        return list_folder_tree(self.root)

    def list_entries(self, folder: str) -> list[str]:
        folder_path = resolve_nested(self.root, folder)
        if not folder_path.exists():
            return []
        return sorted(p.stem for p in folder_path.glob("*.md"))

    def list_files(self, folder: str) -> list[str]:
        """Every raw, non-.md file directly under `folder` — covers an
        `assets/` directory full of photos/PDFs that were attached to some
        other entry (or never had one), which list_entries() can't surface
        since it only globs *.md. Browse needs this to actually show what's
        inside an assets folder instead of reporting it empty."""
        folder_path = resolve_nested(self.root, folder)
        if not folder_path.exists():
            return []
        return sorted(p.name for p in folder_path.iterdir() if p.is_file() and p.suffix != ".md")

    def read(self, folder: str, slug: str) -> str | None:
        post = self._load(folder, slug)
        return post.content if post is not None else None

    def read_links(self, folder: str, slug: str) -> list[str]:
        post = self._load(folder, slug)
        return (post.metadata.get("links") or []) if post is not None else []

    def read_fields(self, folder: str, slug: str) -> dict:
        """Arbitrary user-defined key/value pairs (e.g. Make/Model/Year on a
        Car entry) — the generic-page-builder equivalent of what a
        domain-specific store (CreditCardStore, InvestmentStore) hardcodes as
        real Pydantic fields. Kept in frontmatter like `links`/`location`."""
        post = self._load(folder, slug)
        return (post.metadata.get("fields") or {}) if post is not None else {}

    def _load(self, folder: str, slug: str) -> frontmatter.Post | None:
        path = resolve_nested(self.root, folder) / f"{slugify(slug)}.md"
        return frontmatter.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def write(
        self,
        folder: str,
        title: str,
        content: str,
        links: list[str] | None = None,
        location: dict | None = None,
        fields: dict | None = None,
    ) -> tuple[str, str]:
        """`links`/`location`/`fields` left as None mean "don't touch" —
        any existing value for that key is carried over from the file on
        disk rather than wiped. Without this, a plain body edit (Browse's
        raw-text save, which only ever sends new content) would silently
        blank out an AI-computed links list or the generic page builder's
        fields every time — same class of bug as the CreditCard/Investment
        stores' partial-update fix, just at the KBStore level this time."""
        folder_path = resolve_nested(self.root, folder)
        entry_slug = slugify(title)
        folder_path.mkdir(parents=True, exist_ok=True)
        path = folder_path / f"{entry_slug}.md"
        existing = frontmatter.loads(path.read_text(encoding="utf-8")) if path.exists() else None
        post = frontmatter.Post(f"# {title}\n\n{content}\n")
        if existing is not None:
            post.metadata.update(existing.metadata)
        post["links"] = links if links is not None else (post.metadata.get("links") or [])
        # Where this was taken (EXIF GPS, deterministic) — like links, kept
        # in metadata rather than the body so it never touches a "keep as
        # is" document's content. Groundwork for later date+location+journal
        # query features, not surfaced anywhere yet beyond the graph.
        if location is not None:
            post["location"] = location
        if fields is not None:
            post["fields"] = fields
        path.write_text(frontmatter.dumps(post), encoding="utf-8")
        # Return the actual slugified path (each segment lowercased/hyphenated)
        # so callers know exactly where it landed, not the raw input string.
        folder_slug = str(folder_path.relative_to(self.root)).replace("\\", "/")
        return folder_slug, entry_slug

    def notes_index(self) -> list[dict]:
        """{folder, slug, title} for every entry — enough context for AI to
        propose relevant [[links]] without dumping full KB content into the
        prompt (that's what the KB chat does; this stays cheap for a link
        pass that runs on every single drop)."""
        index = []
        for folder in self.list_folders():
            for slug in self.list_entries(folder):
                content = self.read(folder, slug)
                if not content:
                    continue
                title = content.split("\n", 1)[0].lstrip("# ").strip() or slug
                index.append({"folder": folder, "slug": slug, "title": title})
        return index

    def graph_entries(self) -> list[dict]:
        """{folder, slug, title, links, asset} for every entry — the full
        node+edge data the graph view needs, one read pass per entry."""
        entries = []
        for folder in self.list_folders():
            for slug in self.list_entries(folder):
                post = self._load(folder, slug)
                if post is None:
                    continue
                title = post.content.split("\n", 1)[0].lstrip("# ").strip() or slug
                asset_match = _ASSET_RE.search(post.content)
                entries.append(
                    {
                        "folder": folder,
                        "slug": slug,
                        "title": title,
                        "links": post.metadata.get("links") or [],
                        "asset": asset_match.group(1) if asset_match else None,
                        "location": post.metadata.get("location"),
                    }
                )
        return entries

    def save_asset(self, folder: str, filename: str, data: bytes) -> str:
        """Saves a binary file (photo/PDF/DOCX/STL) into <folder>/assets/ —
        same 'copy the folder, it's self-contained' pattern already used for
        logs/ and presets/ elsewhere in the KB tree. Returns the path relative
        to the folder (e.g. "assets/deadlift-form.jpg") for the markdown
        entry to reference."""
        assets_dir = resolve_nested(self.root, folder) / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        stem, _, ext = filename.rpartition(".")
        safe_name = f"{slugify(stem or filename)}.{ext.lower()}" if ext else slugify(filename)
        (assets_dir / safe_name).write_bytes(data)
        return f"assets/{safe_name}"

    def read_asset(self, folder: str, asset_path: str) -> bytes | None:
        path = resolve_nested(self.root, folder) / asset_path
        return path.read_bytes() if path.exists() else None

    def add_asset_to_entry(self, folder: str, slug: str, filename: str, data: bytes) -> str:
        """Attaches a NEW file to an already-existing entry — distinct from
        save_asset() (just writes bytes, caller wires up the [asset](...)
        line itself) and replace_asset() (overwrites bytes at an existing
        path in place). This appends a fresh asset line to the entry's body
        and preserves the rest of its frontmatter (links/location/fields),
        the same merge-safe pattern write() uses."""
        post = self._load(folder, slug)
        if post is None:
            raise FileNotFoundError(f"entry not found: {folder}/{slug}")
        asset_path = self.save_asset(folder, filename, data)
        post.content = post.content.rstrip("\n") + f"\n[asset]({asset_path})\n"
        path = resolve_nested(self.root, folder) / f"{slugify(slug)}.md"
        path.write_text(frontmatter.dumps(post), encoding="utf-8")
        return asset_path

    def replace_asset(self, folder: str, asset_path: str, data: bytes) -> None:
        """Overwrites an asset's bytes IN PLACE at its existing path — unlike
        save_asset(), which derives a fresh (possibly different) filename
        from whatever's uploaded, this keeps the exact path the markdown
        entry's [asset](...) link already points to, so "replace this file
        with a newer version" never breaks the link."""
        path = resolve_nested(self.root, folder) / asset_path
        if not path.parent.exists():
            raise FileNotFoundError(f"asset folder does not exist: {path.parent}")
        path.write_bytes(data)
