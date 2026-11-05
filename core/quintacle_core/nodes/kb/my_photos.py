"""The owner's OWN photos inline in chat (2026-11-05).

"show me photos from Vienna" used to get Wikipedia pictures ({{photo:Name}})
at best — the real photo notes were in the context (retrieval hits, and the
place hierarchy's located_in members as neighbors) but only as text. Now:

1. context assembly (chat._kb_context) hands every retrieved photo note — a
   hit or a neighbor, ALWAYS through the request's PrivacyGate — to a
   per-request `PhotoRegistry`, which gives it a short stable handle (P1,
   P2…) and renders one block listing them with a one-sentence instruction:
   write `{{myphoto:P3}}` on its own line to show it. The instruction lives in
   the context block itself, so every provider gets it, and only when there
   is a photo to show.
2. after the reply, code (`render_my_photos`) swaps each tag for a markdown
   image whose src is the backend asset route
   `/kb/asset?folder=…&path=…&open=<slug>` (validate_reply_links already
   checks that route exists; ChatLog resolves it against API_BASE and uses
   `open` for the Browse link). Unknown handles vanish silently.
3. deterministic fallback for weak/local models: when the user clearly asked
   for photos and the reply showed none, code appends a gallery of the best
   matching handles (max 6).

Privacy: only gate-admitted nodes ever register, so a cloud request's map
(and therefore its context and its reply) never holds a private photo; a
local request may (and the gate records it in `used` as usual).
"""
from __future__ import annotations

import re
import urllib.parse

from .privacy import note_parts
from .store import _ASSET_LINES_RE, KBStore, _frontmatter_assets

MYPHOTO_TAG_RE = re.compile(r"\{\{\s*myphoto\s*:\s*([A-Za-z0-9]+)\s*\}\}")
_IMAGE_EXTS = {"jpg", "jpeg", "png", "webp", "gif", "avif"}
_MAX_REGISTERED = 24  # photos listed in one turn's context
_FALLBACK_MAX = 6

# "show me photos from Vienna", "pics with Rahul", "any pictures of Prague?"
_ASKS_FOR_PHOTOS_RE = re.compile(r"\b(photos?|pics?|pictures?|images?|snaps?|selfies?)\b", re.IGNORECASE)
_STOP = {
    "photo", "photos", "pic", "pics", "picture", "pictures", "image", "images", "snap", "snaps",
    "selfie", "selfies", "show", "me", "my", "from", "with", "of", "in", "the", "a", "an", "and",
    "any", "some", "all", "i", "took", "do", "have", "what", "when", "where", "at", "on", "to",
}

PHOTO_RULE = (
    "These are the user's OWN photos (handles in brackets). To show one, write "
    "{{myphoto:P1}} (its handle) on its own line — the app replaces it with the actual "
    "image; never invent a handle, and only show photos that fit the question."
)


def asks_for_photos(text: str) -> bool:
    return bool(_ASKS_FOR_PHOTOS_RE.search(text or ""))


def _image_asset(store: KBStore, folder: str, slug: str) -> tuple[dict, str] | None:
    """(raw frontmatter, first existing image asset path) or None."""
    meta = store.read_meta(folder, slug)
    content = store.read(folder, slug)
    if meta is None or content is None:
        return None
    for asset in [*_frontmatter_assets(meta), *_ASSET_LINES_RE.findall(content)]:
        asset = str(asset).strip()
        if asset.rpartition(".")[2].lower() in _IMAGE_EXTS and store.asset_exists(folder, asset):
            return meta, asset
    return None


def _clean(text: str) -> str:
    """Safe inside markdown alt text / one context line."""
    return re.sub(r"[\[\]\n\r()]+", " ", str(text)).strip()


def _label_parts(meta: dict, content: str, title: str) -> tuple[str, str | None, str | None, str | None]:
    place = meta.get("place") if isinstance(meta.get("place"), dict) else {}
    where = ", ".join(str(place[k]) for k in ("city", "country") if place.get(k)) or None
    taken = None
    for fm in meta.get("file_meta") or []:
        if isinstance(fm, dict) and (fm.get("taken") or fm.get("created")):
            taken = str(fm.get("taken") or fm.get("created"))[:10]
            break
    if taken is None:
        for key in ("taken", "date", "created"):
            if meta.get(key):
                taken = str(meta[key])[:10]
                break
    desc = None
    for line in content.split("\n"):
        s = line.strip()
        if not s or s.startswith("#") or _ASSET_LINES_RE.match(s) or "<!--" in s or s.startswith("📍"):
            continue
        desc = s[:120]
        break
    return _clean(title), where and _clean(where), taken, desc and _clean(desc)


class PhotoRegistry:
    """Per-request map handle → photo. Register only what the gate admitted."""

    def __init__(self) -> None:
        self.photos: dict[str, dict] = {}  # handle -> {folder, slug, asset, alt, line}
        self._by_node: dict[str, str] = {}

    def register(self, store: KBStore, node_id: str) -> str | None:
        if node_id in self._by_node:
            return self._by_node[node_id]
        if len(self.photos) >= _MAX_REGISTERED:
            return None
        parts = note_parts(node_id)
        if parts is None:
            return None
        folder, slug = parts
        try:
            found = _image_asset(store, folder, slug)
        except Exception:
            return None
        if found is None:
            return None
        meta, asset = found
        content = store.read(folder, slug) or ""
        title = meta.get("title") or (content.lstrip().split("\n", 1)[0].lstrip("# ").strip() if content.lstrip().startswith("#") else slug.replace("-", " ").title())
        title, where, taken, desc = _label_parts(meta, content, title)
        handle = f"P{len(self.photos) + 1}"
        alt = " · ".join(p for p in (where or title, taken) if p)
        line = " · ".join(p for p in (title, where, taken, desc) if p)
        self.photos[handle] = {"folder": folder, "slug": slug, "asset": asset, "alt": alt, "line": line, "id": node_id}
        self._by_node[node_id] = handle
        return handle

    def collect(self, store: KBStore, hits: list[dict], gate) -> None:
        """Every photo note among `hits` and their neighbors, retrieval order.
        `gate` is the request's PrivacyGate — nothing it refuses registers."""
        for hit in hits:
            for node_id in [hit.get("id", ""), *[n.get("id", "") for n in hit.get("neighbors") or []]]:
                node_id = str(node_id)
                if not node_id.startswith("note:") or node_id.startswith("transcript:"):
                    continue
                if gate is not None and not gate.admit(node_id):
                    continue
                self.register(store, node_id)

    def context_block(self) -> str | None:
        if not self.photos:
            return None
        lines = [f"[photo:{h}] {p['line']} (id: {p['id']})" for h, p in self.photos.items()]
        return "## Your photos in this context\n" + PHOTO_RULE + "\n" + "\n".join(lines)

    def markdown(self, handle: str) -> str | None:
        p = self.photos.get(handle)
        if p is None:
            return None
        q = urllib.parse.urlencode({"folder": p["folder"], "path": p["asset"], "open": p["slug"]}, quote_via=urllib.parse.quote)
        return f"![{p['alt'] or handle}](/kb/asset?{q})"

    def best_for(self, query: str, limit: int = _FALLBACK_MAX) -> list[str]:
        """Handles ranked by how many content words of `query` their line
        contains (stable: ties keep retrieval order)."""
        terms = [t for t in re.findall(r"\w+", (query or "").lower()) if t not in _STOP and len(t) > 1]
        order = list(self.photos)
        if terms:
            score = {h: sum(1 for t in terms if t in self.photos[h]["line"].lower()) for h in order}
            if any(score.values()):
                order = [h for h in order if score[h] > 0]
            order.sort(key=lambda h: -score[h])
        return order[:limit]


def render_my_photos(reply: str, registry: PhotoRegistry | None, user_text: str = "") -> str:
    """Replace {{myphoto:Pn}} tags with markdown images (unknown → dropped);
    consecutive photo lines stay one paragraph so ChatLog shows a grid. When
    the user asked for photos and none got shown, append the best matches."""
    if registry is None or not registry.photos:
        return MYPHOTO_TAG_RE.sub("", reply) if "myphoto" in reply else reply
    shown: list[str] = []

    def replace(m: re.Match) -> str:
        md = registry.markdown(m.group(1).upper())
        if md is None:
            return ""
        shown.append(m.group(1).upper())
        return md

    out = MYPHOTO_TAG_RE.sub(replace, reply)
    if shown:
        # tag-per-line → image-per-line; collapse blank lines between images
        out = re.sub(r"(\]\(/kb/asset\?[^)\s]*\))[ \t]*\n(?:[ \t]*\n)+(?=!\[)", r"\1\n", out)
    elif asks_for_photos(user_text):
        picks = registry.best_for(user_text)
        if picks:
            gallery = "\n".join(registry.markdown(h) for h in picks)
            out = f"{out.rstrip()}\n\nYour photos:\n\n{gallery}"
    return out
