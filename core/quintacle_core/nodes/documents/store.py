from __future__ import annotations

from pathlib import Path

import frontmatter

from ...markdown_paths import resolve_nested, slugify

# A fixed home, like Wardrobe/Grooming/logs — not AI-decided (this is a
# structured store with real fields, not a free-form KB note).
_HOME = "Organisation/Document Vault"


class DocumentStore:
    """One markdown file per document (lease, ID, insurance policy, etc.) —
    real structured fields (doc_type, issued/expiry dates, status) plus an
    optional attached scan/photo, same asset pattern as KBStore.save_asset.
    Markdown is the source of truth; no SQLite mirror, same reasoning as
    Wardrobe/Grooming/Routines — nothing else holds a foreign key into a
    document."""

    def __init__(self, kb_root: Path):
        self.kb_root = Path(kb_root)

    def _dir(self) -> Path:
        path = resolve_nested(self.kb_root, _HOME)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def write(
        self,
        name: str,
        doc_type: str = "",
        issued_date: str | None = None,
        expiry_date: str | None = None,
        status: str = "active",
        notes: str = "",
        assets: list[str] | None = None,
    ) -> str:
        slug = slugify(name)
        post = frontmatter.Post(notes)
        post["name"] = name
        post["doc_type"] = doc_type
        post["issued_date"] = issued_date
        post["expiry_date"] = expiry_date
        post["status"] = status
        if assets:
            post["assets"] = assets
        (self._dir() / f"{slug}.md").write_text(frontmatter.dumps(post), encoding="utf-8")
        return slug

    # A file in this folder not written by write() (e.g. a plain KB note that
    # got misfiled here before document-vs-note routing existed, or a hand
    # edit via Browse Files) shouldn't crash the whole feature just because
    # it lacks doc_type/status/name — fall back to sane defaults instead.
    def _normalize(self, post: frontmatter.Post, stem: str) -> dict:
        # `assets` is the current, unbounded-length field. Documents written
        # before this existed only have the old fixed `asset`/`asset2` pair —
        # read those as a fallback so nothing already on disk goes invisible.
        assets = post.metadata.get("assets") or [a for a in (post.metadata.get("asset"), post.metadata.get("asset2")) if a]
        return {
            "doc_type": "",
            "status": "active",
            **post.metadata,
            "name": post.metadata.get("name") or stem.replace("-", " ").title(),
            "notes": post.content,
            "slug": stem,
            "assets": assets,
        }

    def all(self) -> list[dict]:
        results = []
        for p in sorted(self._dir().glob("*.md")):
            post = frontmatter.loads(p.read_text(encoding="utf-8"))
            results.append(self._normalize(post, p.stem))
        return results

    def get(self, name: str) -> dict | None:
        path = self._dir() / f"{slugify(name)}.md"
        if not path.exists():
            return None
        post = frontmatter.loads(path.read_text(encoding="utf-8"))
        return self._normalize(post, path.stem)

    def delete(self, name: str) -> None:
        path = self._dir() / f"{slugify(name)}.md"
        if path.exists():
            path.unlink()

    def save_asset(self, filename: str, data: bytes) -> str:
        assets_dir = self._dir() / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        stem, _, ext = filename.rpartition(".")
        safe_name = f"{slugify(stem or filename)}.{ext.lower()}" if ext else slugify(filename)
        (assets_dir / safe_name).write_bytes(data)
        return f"assets/{safe_name}"

    def read_asset(self, asset_path: str) -> bytes | None:
        path = self._dir() / asset_path
        return path.read_bytes() if path.exists() else None
