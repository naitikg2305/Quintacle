"""Code-side web search for models WITHOUT native search (local Ollama, Bedrock).

Deterministic core, models at the edges (2026-11-05): CODE builds the query,
searches, and fetches pages; the model only reads the finished results.
Cloud Claude / GPT / Max keep their own native search tools — this lane
never runs for them.

Privacy: the ONLY thing that leaves the machine is the search query, and
the query is derived purely from the user's newest typed message (filler
stripped). Note content, KB context, private notes and earlier turns are
never part of it. The fetched pages are then read locally.

Backends (stdlib only — phone/Termux-safe, no new deps):
  - DuckDuckGo's HTML endpoint, parsed with html.parser (default)
  - SearXNG JSON API when QUINTACLE_SEARXNG_URL is set
Every failure degrades to empty results; nothing here raises into chat.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, wait
from html import unescape
from html.parser import HTMLParser

logger = logging.getLogger(__name__)

DDG_URL = "https://html.duckduckgo.com/html/?q="
SEARCH_TIMEOUT = 8.0
FETCH_TIMEOUT = 8.0
TOTAL_BUDGET = 20.0
PAGE_CHARS = 3000
FETCH_TOP = 3
_UA = "Mozilla/5.0 (X11; Linux x86_64) Quintacle/1.0"

# Providers whose chat path has NO built-in web search — the only ones this
# lane serves. anthropic/openai/max search natively.
NO_NATIVE_SEARCH = frozenset({"local", "bedrock"})


def _get(url: str, timeout: float) -> tuple[str, str]:
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept-Language": "en-US,en;q=0.8"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — http(s) only, checked by callers
        ctype = resp.headers.get("Content-Type", "") if getattr(resp, "headers", None) else ""
        raw = resp.read(2_000_000)
    charset = "utf-8"
    m = re.search(r"charset=([\w-]+)", ctype or "")
    if m:
        charset = m.group(1)
    return raw.decode(charset, errors="replace"), ctype or ""


# --- search ----------------------------------------------------------------


class _DDGParser(HTMLParser):
    """Pulls (title, href, snippet) out of DuckDuckGo's HTML results page:
    `a.result__a` is the title link, `.result__snippet` the snippet."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[dict] = []
        self._field: str | None = None
        self._buf: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = (a.get("class") or "").split()
        if tag == "a" and "result__a" in cls:
            self.results.append({"title": "", "url": _ddg_href(a.get("href") or ""), "snippet": ""})
            self._field, self._buf = "title", []
        elif "result__snippet" in cls and self.results:
            self._field, self._buf = "snippet", []

    def handle_endtag(self, tag):
        if self._field and tag in ("a", "div", "td", "span"):
            self.results[-1][self._field] = " ".join("".join(self._buf).split())
            self._field = None

    def handle_data(self, data):
        if self._field:
            self._buf.append(data)


def _ddg_href(href: str) -> str:
    """DDG wraps targets as //duckduckgo.com/l/?uddg=<encoded>; unwrap them."""
    if href.startswith("//"):
        href = "https:" + href
    parsed = urllib.parse.urlparse(href)
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        target = urllib.parse.parse_qs(parsed.query).get("uddg")
        if target:
            return target[0]
    return href


def parse_ddg_html(html: str, k: int = 5) -> list[dict]:
    p = _DDGParser()
    try:
        p.feed(html)
    except Exception:  # malformed markup — keep what parsed
        pass
    out = []
    for r in p.results:
        if not r["url"].startswith(("http://", "https://")) or "duckduckgo.com/y.js" in r["url"]:
            continue  # ads / internal links
        if any(o["url"] == r["url"] for o in out):
            continue
        out.append(r)
        if len(out) >= k:
            break
    return out


BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"


def backend() -> str | None:
    """Which search backend is configured (2026-11-05 correction). Live check
    showed DuckDuckGo's HTML endpoint answers scripted requests with a bot
    challenge (0 results) — scraping around that isn't acceptable, so the
    default is now an API made for programs:
      1. SearXNG you host yourself (QUINTACLE_SEARXNG_URL), else
      2. Brave Search API (QUINTACLE_BRAVE_API_KEY; free tier), else
      3. the DDG HTML parser ONLY if explicitly chosen (QUINTACLE_WEB_BACKEND=ddg),
      else None — the chat lane then says web search isn't configured."""
    if os.environ.get("QUINTACLE_SEARXNG_URL", "").strip():
        return "searxng"
    if os.environ.get("QUINTACLE_BRAVE_API_KEY", "").strip():
        return "brave"
    if os.environ.get("QUINTACLE_WEB_BACKEND", "").strip().lower() == "ddg":
        return "ddg"
    return None


def _brave(query: str, k: int, timeout: float) -> list[dict]:
    url = BRAVE_URL + "?" + urllib.parse.urlencode({"q": query, "count": max(1, min(k, 20))})
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "X-Subscription-Token": os.environ["QUINTACLE_BRAVE_API_KEY"].strip(),
            "User-Agent": "Quintacle/1.0 (personal assistant)",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8", "replace"))
    return [
        {"title": r.get("title", ""), "url": r.get("url", ""), "snippet": html_to_text(r.get("description", "") or "")}
        for r in (data.get("web") or {}).get("results", [])
        if str(r.get("url", "")).startswith(("http://", "https://"))
    ][:k]


def search(query: str, k: int = 5, timeout: float = SEARCH_TIMEOUT) -> list[dict]:
    """[{title, url, snippet}] — empty on any failure or when no backend is
    configured (see backend())."""
    query = (query or "").strip()
    if not query:
        return []
    which = backend()
    try:
        if which == "searxng":
            searx = os.environ["QUINTACLE_SEARXNG_URL"].strip()
            url = searx.rstrip("/") + "/search?" + urllib.parse.urlencode({"q": query, "format": "json"})
            body, _ = _get(url, timeout)
            data = json.loads(body)
            return [
                {"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("content", "")}
                for r in data.get("results", [])
                if str(r.get("url", "")).startswith(("http://", "https://"))
            ][:k]
        if which == "brave":
            return _brave(query, k, timeout)
        if which == "ddg":
            body, _ = _get(DDG_URL + urllib.parse.quote_plus(query), timeout)
            return parse_ddg_html(body, k)
        return []
    except Exception as e:
        logger.info("web search failed: %s", e)
        return []


# --- fetch -----------------------------------------------------------------

_SKIP_TAGS = {"script", "style", "noscript", "nav", "header", "footer", "aside", "form", "svg", "iframe", "template", "button"}
_BLOCK_TAGS = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section", "article", "pre", "blockquote"}


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP_TAGS:
            self._skip += 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_startendtag(self, tag, attrs):
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in _SKIP_TAGS and self._skip:
            self._skip -= 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    p = _TextParser()
    try:
        p.feed(html)
    except Exception:
        pass
    lines = (" ".join(line.split()) for line in "".join(p.parts).splitlines())
    return "\n".join(line for line in lines if line)


def fetch_text(url: str, max_chars: int = PAGE_CHARS, timeout: float = FETCH_TIMEOUT) -> str:
    """Readable text of one page (scripts/nav stripped), capped — "" on failure."""
    if not url.startswith(("http://", "https://")):
        return ""
    try:
        body, ctype = _get(url, timeout)
    except Exception as e:
        logger.info("web fetch failed for %s: %s", url, e)
        return ""
    text = html_to_text(body) if ("html" in ctype or "<" in body[:500]) else unescape(body)
    text = text.strip()
    if len(text) > max_chars:
        text = text[:max_chars].rsplit(" ", 1)[0] + " …"
    return text


# --- the chat lane ---------------------------------------------------------

# Clear "needs current/external info" cues.
_EXTERNAL_CUE = re.compile(
    r"https?://\S+|\b(latest|today'?s?|tonight|this week|current(ly)?|right now|news|headlines?|"
    r"price of|prices?|cost of|how much (is|are|does)|stock|exchange rate|opening hours|open (now|today|on)|"
    r"hours of|how do i|how to|visa|requirements?|weather|forecast|near me|nearby|"
    r"release date|score|schedule for|who won|look (it )?up|search (the web|online|for)|google)\b",
    re.I,
)
# Owner's-own-data cues — with these and no external cue, auto stays off.
_OWN_DATA = re.compile(r"\b(my|mine|me|i|i'm|i've|i'd|we|our|us)\b", re.I)
# Even with "my", these phrasings still clearly want the outside world.
_STRONG_EXTERNAL = re.compile(r"https?://\S+|\b(news|weather|forecast|visa|price of|exchange rate|opening hours|near me|search (the web|online)|look (it )?up)\b", re.I)


def needs_web(text: str) -> bool:
    """Deterministic auto-on heuristic. Off for messages about the owner's
    own data ("my notes", "I", "my trip") unless a strong external cue is
    present (a URL, weather, visa, news, near me...)."""
    text = text or ""
    if _STRONG_EXTERNAL.search(text):
        return True
    if not _EXTERNAL_CUE.search(text):
        return False
    # "how do I…" / "where can I…" are generic how-tos, not the owner's data.
    rest = re.sub(r"\b(how|where|what|when|can|should|could)( \w+)? (do|can|should|would|could)? ?i\b", " ", text, flags=re.I)
    return not _OWN_DATA.search(rest)


_FILLER = re.compile(
    r"^\s*(hey|hi|hello|ok(ay)?|so|um+|please|pls|quick question)[,!.\s]+|"
    r"\b(can|could|would|will) you (please )?(tell me|find( out)?|look up|search( for)?|check|google)\b|"
    r"\b(please|pls|for me|thanks|thank you|i (want|need) to know|i'?m wondering|do you know)\b|"
    r"\b(search (the web|online) (for)?|look (it )?up|on the (web|internet))\b",
    re.I,
)


def build_query(text: str, max_chars: int = 200) -> str:
    """The search query: the user's message with filler stripped. Nothing
    else goes in — no notes, no context, no earlier turns."""
    q = re.sub(r"https?://\S+", " ", text or "")
    prev = None
    while prev != q:
        prev, q = q, _FILLER.sub(" ", q)
    q = " ".join(q.replace("?", " ").split()).strip(" ,.!")
    return q[:max_chars].strip()


def web_block(user_text: str, *, k: int = 5, budget: float = TOTAL_BUDGET) -> str | None:
    """Search + fetch the top pages in parallel; the "Web results" context
    block with numbered sources, or None when nothing came back. Explicit
    URLs in the message are fetched directly (as sources 1..n)."""
    start = time.monotonic()
    urls = re.findall(r"https?://[^\s)>\]]+", user_text or "")
    results: list[dict] = [{"title": u, "url": u, "snippet": ""} for u in urls[:FETCH_TOP]]
    query = build_query(user_text)
    if query and len(results) < k:
        for r in search(query, k):
            if all(r["url"] != o["url"] for o in results):
                results.append(r)
    results = results[:k]
    if not results:
        return None
    texts: dict[int, str] = {}
    remaining = max(1.0, budget - (time.monotonic() - start))
    pool = ThreadPoolExecutor(max_workers=FETCH_TOP)
    futs = {pool.submit(fetch_text, r["url"], PAGE_CHARS, min(FETCH_TIMEOUT, remaining)): i for i, r in enumerate(results[:FETCH_TOP])}
    done, _ = wait(futs, timeout=remaining)
    for f in done:
        try:
            texts[futs[f]] = f.result()
        except Exception:
            pass
    pool.shutdown(wait=False, cancel_futures=True)
    parts = [f"## Web results (fetched just now) — search query: \"{query}\""]
    for i, r in enumerate(results):
        body = texts.get(i) or r.get("snippet") or ""
        if not body and not r.get("title"):
            continue
        parts.append(f"[{i + 1}] {r.get('title') or r['url']} — {r['url']}\n{body}".rstrip())
    if len(parts) == 1:
        return None
    parts.append(
        "Use these web results for outside/current facts. Cite them inline as [1], [2] "
        "and list the sources you used as markdown links at the end, e.g. [1] [Title](url). "
        "If the results don't answer the question, say so plainly instead of guessing."
    )
    return "\n\n".join(parts)


def chat_web_block(provider: str, web: bool | None, user_text: str, mode: str = "unserious") -> str | None:
    """The chat lane's single entry point. `web`: True = force on, False =
    force off, None = auto heuristic (never auto in serious mode). Only
    providers WITHOUT native search get a block."""
    if provider not in NO_NATIVE_SEARCH or web is False:
        return None
    if os.environ.get("QUINTACLE_WEB_SEARCH", "").strip().lower() in ("off", "0", "false", "no"):
        return None  # global kill switch (the test suite sets it)
    if web is None and (mode == "serious" or not needs_web(user_text)):
        return None
    if backend() is None and not re.search(r"https?://", user_text or ""):
        # No search API set up: say so when the owner explicitly asked for the
        # web; stay silent on auto so ordinary chats aren't cluttered.
        if web is True:
            return (
                "## Web search unavailable\nWeb search isn't configured on this device (no search API). "
                "Tell the user briefly that you couldn't search the web, then answer from what you know, "
                "clearly marked as possibly out of date."
            )
        return None
    try:
        return web_block(user_text)
    except Exception as e:  # belt and braces — never break chat
        logger.info("web lane failed: %s", e)
        return None
