from __future__ import annotations

import base64
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

import anthropic
from openai import OpenAI

from ...llm_config import DEFAULT_MODEL, RESEARCH_MODEL
from .store import KBStore

_PHOTO_TAG_RE = re.compile(r"\{\{photo:([^}]+)\}\}")

_PHOTO_INSTRUCTION = (
    "When you mention a real, concrete, specific thing that a photo or "
    "diagram would genuinely help illustrate — not just travel landmarks, "
    "but objects, technical/scientific topics, historical events, "
    "organisms, machinery, chemicals, anything with a real Wikipedia "
    "article that likely has an infobox image — tag it immediately after "
    "the name with {{photo:Exact Name}}, using the name's real Wikipedia "
    "article title (e.g. \"Jet fuel\", \"Mitochondria\", \"Eiffel Tower\"). "
    "Use it whenever it would genuinely help the reader, not just for "
    "travel content — but skip it entirely for short, simple, or purely "
    "conversational answers (a one-word reply never needs a photo). Don't tag vague/abstract concepts, people, or "
    "anything you're not reasonably confident has a real Wikipedia page "
    "with an image — a missing image is a silently dropped tag, but an "
    "irrelevant one still looks sloppy."
)


def _fetch_wikipedia_thumbnail(name: str) -> str | None:
    """A free, keyless image lookup for named real-world places/things —
    Wikipedia's REST summary endpoint returns a representative photo for
    most notable landmarks. Not a general image search (no coverage for
    obscure/local places), but exactly right for "illustrate the famous
    thing I just mentioned" in a travel itinerary or similar."""
    url = "https://en.wikipedia.org/api/rest_v1/page/summary/" + urllib.parse.quote(name.strip().replace(" ", "_"))
    req = urllib.request.Request(url, headers={"User-Agent": "Quintacle/1.0 (personal life-management app)"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.load(resp)
    except Exception:
        return None
    thumbnail = data.get("thumbnail") or {}
    return thumbnail.get("source")


def _resolve_photo_tags(text: str) -> str:
    """Replaces every {{photo:Name}} tag the model emitted with a real
    inline markdown image (rendered by the existing ReactMarkdown chat
    view, no frontend change needed) — or strips the tag silently if no
    photo was found, rather than leaving a raw tag visible."""
    cache: dict[str, str | None] = {}

    def replace(match: re.Match) -> str:
        name = match.group(1).strip()
        if name not in cache:
            cache[name] = _fetch_wikipedia_thumbnail(name)
        url = cache[name]
        return f"![{name}]({url})" if url else ""

    return _PHOTO_TAG_RE.sub(replace, text)


def _render_entry(store: KBStore, folder: str, slug: str, content: str) -> str:
    fields = store.read_fields(folder, slug)
    if not fields:
        return f"### {folder}/{slug}\n{content}"
    field_lines = "\n".join(f"- {k}: {v}" for k, v in fields.items())
    return f"### {folder}/{slug}\n{field_lines}\n\n{content}"


def _kb_context_everything(store: KBStore) -> str:
    """The ORIGINAL dump-everything context — kept strictly as the fallback
    for when the retrieval index isn't available (uninitialized process,
    never backfilled, or any retrieval error). The default path is the
    retrieval-grounded `_kb_context` below (rebuilt 2026-10-19 — the owner
    explicitly opened the chat-context logic for the §3/§4 wave)."""
    sections = []
    for folder in store.list_folders():
        for slug in store.list_entries(folder):
            content = store.read(folder, slug)
            if content:
                sections.append(_render_entry(store, folder, slug, content))
    return "\n\n".join(sections) if sections else "(the knowledge base is empty right now)"


# --- retrieval-grounded context (REBUILT 2026-10-19, next-wave-plan §3+§4) ---
#
# index→select→fetch instead of dump-everything: retrieve() (FTS5 + optional
# vectors + graph expansion, all deterministic code) picks ~K nodes for the
# user's latest question; only THOSE get fetched in full. Structured rows
# (expenses, meals, workouts...) enter as their already-computed one-line
# summaries — finished numbers from SQLite, never re-derived by the model.
# Each hit carries its 1-hop neighbor labels (title + edge type + id) as
# plain context lines; the chat loop is single-shot (no tool turns), so a
# neighbor the model wants is something it ASKS the user to bring up next.

_RETRIEVE_K = 8
_FULL_BODY_CHARS = 4000  # per-hit cap on a prose node's full content
_TOPIC_BODY_CHARS = 8000  # the scoped topic note itself gets more room
_CONTEXT_CHAR_BUDGET = 24000  # total cap on the assembled context block


def _last_user_text(messages: list[dict]) -> str:
    """The retrieval query: the newest user turn's typed text. Only real text
    blocks count — attachment placeholders would just pollute the FTS query."""
    for m in reversed(messages):
        if m.get("role") != "user":
            continue
        content = m.get("content") or ""
        if isinstance(content, str):
            text = content.strip()
        else:
            text = "\n".join(b.get("text", "") for b in content if b.get("type") == "text").strip()
        if text:
            return text
    return ""


def _neighbor_line(neighbors: list[dict]) -> str:
    if not neighbors:
        return ""
    parts = [f"{n['title']} ({n['edge_type']}, id: {n['id']})" for n in neighbors]
    return "Connected: " + "; ".join(parts)


def _prose_body(store: KBStore, hit_id: str, cap: int) -> str | None:
    """Full content for a prose hit — notes/places/people (all `note:` ids)
    read from the KB store with their freeform fields, journal days from the
    journal store. None = the caller falls back to the hit's summary line."""
    kind, _, rest = hit_id.partition(":")
    if kind == "note":
        folder, _, slug = rest.rpartition("/")
        if not folder:
            return None
        content = store.read(folder, slug)
        if not content:
            return None
        if content.startswith("# "):  # the title heading is already the section header
            content = content.partition("\n")[2].lstrip("\n")
        fields = store.read_fields(folder, slug)
        field_lines = "\n".join(f"- {k}: {v}" for k, v in fields.items())
        body = f"{field_lines}\n\n{content}" if field_lines else content
        return body[:cap]
    if kind == "journal":
        try:
            from datetime import date as _date
            from ..journal.api import get_store as get_journal_store

            content = get_journal_store().load(_date.fromisoformat(rest))
        except Exception:
            return None  # journal store not wired / bad id — summary line serves
        return content[:cap] if content else None
    return None


_PROSE_TYPES = {"note", "place", "person", "journal_day"}


def _hit_section(store: KBStore, hit: dict, *, with_body: bool) -> str:
    """One retrieved node as context. Prose nodes (notes, places, people,
    journal days) get their FULL current content (capped); everything else —
    log rows, meals, routines, todos, events — is its finished one-line
    summary, passed through as-is (the numbers in it were computed in SQL;
    the model never re-derives them)."""
    lines = [f"### {hit['title']} [{hit['id']}] ({hit['type']})"]
    body = _prose_body(store, hit["id"], _FULL_BODY_CHARS) if (with_body and hit["type"] in _PROSE_TYPES) else None
    if body:
        lines.append(body)
    elif hit.get("summary"):
        lines.append(hit["summary"])
    neighbor = _neighbor_line(hit.get("neighbors") or [])
    if neighbor:
        lines.append(neighbor)
    return "\n".join(lines)


def _kb_context(store: KBStore, query: str, exclude_id: str | None = None) -> str:
    """The rebuilt context: retrieve(query, k≈8), fetch full content only for
    the selected prose hits, finished summary lines for structured rows,
    1-hop neighbor labels per hit. Deterministic assembly in retrieve()'s own
    order (RRF score desc, id tiebreak) under a chars budget — a hit whose
    full body would blow the budget degrades to its summary line, never a
    reshuffle. Raises when retrieval is unusable (uninitialized or empty
    index) so _system_text can fall back to the legacy behavior."""
    from ...retrieval import get_retrieval_index

    index = get_retrieval_index()  # RuntimeError when never initialized
    if not index.counts_by_type():
        # An existing-but-empty index (fresh process over an old store that
        # was never backfilled) must not silently answer "nothing matched".
        raise LookupError("retrieval index is empty — run the backfill")
    hits = [h for h in index.retrieve(query, k=_RETRIEVE_K) if h["id"] != exclude_id]
    if not hits:
        return "(nothing in the knowledge base matched this question)"
    sections: list[str] = []
    total = 0
    for hit in hits:
        section = _hit_section(store, hit, with_body=True)
        if total + len(section) > _CONTEXT_CHAR_BUDGET:
            section = _hit_section(store, hit, with_body=False)
            if total + len(section) > _CONTEXT_CHAR_BUDGET:
                break
        sections.append(section)
        total += len(section)
    return "\n\n".join(sections)


def _topic_context(store: KBStore, folder: str, slug: str) -> str | None:
    """Topic hydration (next-wave-plan §4): a chat opened ON a note starts
    from that node's current state — full content + fields + its graph
    neighborhood labels — never from any saved transcript (those are
    second-tier by decision, reachable only via the explicit search lane)."""
    content = store.read(folder, slug)
    if content is None:
        return None
    first_line, _, rest = content.partition("\n")
    title = first_line.lstrip("# ").strip() or slug
    fields = store.read_fields(folder, slug)
    field_lines = "\n".join(f"- {k}: {v}" for k, v in fields.items())
    body = rest.lstrip("\n")
    body = f"{field_lines}\n\n{body}" if field_lines else body
    lines = [f"## Current topic: {title} [note:{folder}/{slug}]", body[:_TOPIC_BODY_CHARS]]
    try:
        from ...retrieval import neighbor_labels

        neighbor = _neighbor_line(neighbor_labels(f"note:{folder}/{slug}"))
    except Exception:
        neighbor = ""
    if neighbor:
        lines.append(neighbor)
    return "\n".join(line for line in lines if line)


def _kb_context_for_folder(store: KBStore, folder: str) -> str:
    """Same shape as _kb_context(), but only entries filed under `folder` or
    one of its subfolders — a scoped chat about one specific parent
    directory (e.g. a person's folder) shouldn't have your entire KB in
    context, and definitely shouldn't be able to see the answer come from
    somewhere it can't cite."""
    sections = []
    for f in store.list_folders():
        if f != folder and not f.startswith(folder + "/"):
            continue
        for slug in store.list_entries(f):
            content = store.read(f, slug)
            if content:
                sections.append(_render_entry(store, f, slug, content))
    return "\n\n".join(sections) if sections else f"(nothing filed under {folder} yet)"


# The chat's model picker. Anthropic models go through the anthropic SDK
# (server-side web_search tool); OpenAI models go through the Responses API
# (its own web_search tool); Bedrock models go through AWS (see _run_bedrock —
# the anthropic SDK's Bedrock client for Claude-family IDs, boto3's Converse
# API for everything else); local models go through the Ollama daemon's HTTP
# API on this machine (see _run_local — no tokens billed, no network). All
# take the same Anthropic-shaped message list from the frontend — the
# OpenAI/Converse/Ollama paths convert it.
# `price` is $/1M tokens in/out, shown in the dropdown so the cost is visible;
# Bedrock entries bill through AWS, so the dropdown just says so; local
# entries are free.
CHAT_MODELS: list[dict] = [
    {"id": "claude-haiku-4-5", "label": "Claude Haiku 4.5", "provider": "anthropic", "price": "$1 / $5"},
    {"id": "claude-haiku-5-5", "label": "Claude Haiku 5.5", "provider": "anthropic", "price": "$0.10 / $0.50"},
    {"id": "claude-sonnet-5", "label": "Claude Sonnet 5", "provider": "anthropic", "price": "$2 / $10"},
    {"id": "claude-sonnet-5-5", "label": "Claude Sonnet 5.5", "provider": "anthropic", "price": "$2 / $10"},
    {"id": "claude-opus-5", "label": "Claude Opus 5", "provider": "anthropic", "price": "$5 / $25"},
    {"id": "claude-opus-5-5", "label": "Claude Opus 5.5", "provider": "anthropic", "price": "$4 / $20"},
    {"id": "gpt-4o-mini", "label": "GPT-4o mini", "provider": "openai", "price": "$0.15 / $0.60"},
    {"id": "gpt-5-nano", "label": "GPT-5 nano", "provider": "openai", "price": "$0.05 / $0.40"},
    {"id": "gpt-5-mini", "label": "GPT-5 mini", "provider": "openai", "price": "$0.25 / $2"},
    {"id": "bedrock:anthropic.claude-sonnet-5-5", "label": "Claude Sonnet 5.5 (Bedrock)", "provider": "bedrock", "price": "AWS billing"},
    {"id": "bedrock:us.amazon.nova-lite-v1:0", "label": "Amazon Nova Lite (Bedrock)", "provider": "bedrock", "price": "AWS billing"},
    # Local models via Ollama — curated to what's actually pulled on this
    # machine. The 1.5B is the phone-class candidate (prove the 1-2B tier
    # here, run it on-device later); the 8B is the comfortable desktop pick.
    {"id": "local:qwen2.5:1.5b", "label": "Qwen2.5 1.5B (local)", "provider": "local", "price": "free"},
    {"id": "local:qwen3:4b", "label": "Qwen3 4B (local)", "provider": "local", "price": "free"},
    {"id": "local:qwen3:8b", "label": "Qwen3 8B (local)", "provider": "local", "price": "free"},
]
_MODELS_BY_ID = {m["id"]: m for m in CHAT_MODELS}

# Any picker value with this prefix routes to AWS Bedrock; the rest of the
# string is the raw Bedrock model ID. The curated entries above use it too —
# "custom" Bedrock models are the same convention, just typed in by hand.
BEDROCK_PREFIX = "bedrock:"

# Same convention for the local Ollama daemon: "local:<any ollama model>"
# routes to _run_local with the rest of the string as the Ollama model name
# (tags and all, e.g. "local:qwen2.5:1.5b" -> "qwen2.5:1.5b"). Ollama
# validates the name at invoke time, exactly like Bedrock does its IDs.
LOCAL_PREFIX = "local:"

# The dynamic-filtering search variant needs Sonnet 5+; Haiku takes the basic one.
_ANTHROPIC_SEARCH_TYPE = {
    "claude-haiku-4-5": "web_search_20250305",
    "claude-haiku-5-5": "web_search_20250305",
    "claude-sonnet-5": "web_search_20260209",
    "claude-sonnet-5-5": "web_search_20260209",
    "claude-opus-5": "web_search_20260209",
    "claude-opus-5-5": "web_search_20260209",
}

# Opus-tier safety classifiers can decline a request; these models get the
# server-side fallback so a refusal reroutes instead of failing the chat.
_ANTHROPIC_FALLBACK_MODELS = {"claude-opus-5", "claude-opus-5-5"}


class UnknownModelError(ValueError):
    pass


class BedrockError(RuntimeError):
    """A readable, user-facing Bedrock failure (missing AWS credentials, a
    bad/unavailable model ID, region problems) — the API layer turns this
    into a clear chat error instead of a 500 stack trace."""


class OllamaError(RuntimeError):
    """A readable, user-facing local-model failure (the Ollama daemon isn't
    running, the model isn't pulled) — the API layer turns this into a clear
    chat error instead of a 500 stack trace, same deal as BedrockError."""


def resolve_model(model: str | None, research: bool) -> dict:
    """`model` (from the dropdown) wins; otherwise fall back to the old
    research flag so callers that never learned about the picker (the folder
    chat, the read-only chat) keep working on the same defaults as before."""
    wanted = model or (RESEARCH_MODEL if research else DEFAULT_MODEL)
    entry = _MODELS_BY_ID.get(wanted)
    if entry is None and wanted.startswith(BEDROCK_PREFIX):
        # Free-form "bedrock:<raw model id>" — any Bedrock model, not just the
        # curated ones. The raw ID is validated by AWS at invoke time.
        raw = wanted[len(BEDROCK_PREFIX):].strip()
        if raw:
            return {"id": wanted, "label": raw, "provider": "bedrock", "price": "AWS billing"}
    if entry is None and wanted.startswith(LOCAL_PREFIX):
        # Free-form "local:<ollama model>" — any model the daemon has (or can
        # name an error about), not just the curated ones. Same shape as the
        # bedrock: convention above.
        raw = wanted[len(LOCAL_PREFIX):].strip()
        if raw:
            return {"id": wanted, "label": raw, "provider": "local", "price": "free"}
    if entry is None:
        raise UnknownModelError(f"unknown chat model: {wanted}")
    return entry


_GROUNDING_RULES = (
    "Ground your answers in the material below when relevant — reference it "
    "naturally, don't just recite it back. If something isn't covered below, say so "
    "plainly instead of guessing. One-line entries for logged data (expenses, meals, "
    "workouts...) carry numbers already computed from the real records — use them "
    "as-is, never recalculate or re-derive them. \"Connected:\" lines list each "
    "item's graph neighbors by title and id; if one of those looks like it holds the "
    "answer, say so and ask the user to bring it up — you can't fetch it yourself. "
    "This chat is a scratchpad for thinking out loud — nothing here is saved "
    "automatically; the user pushes anything worth keeping into the knowledge base "
    "separately."
)


def _system_text(store: KBStore, use_kb: bool, folder: str | None, slug: str | None, messages: list[dict]) -> str | None:
    """The KB-grounding block, or None when the KB is switched off.

    REBUILT 2026-10-19 (owner opened the chat-context logic — next-wave-plan
    §3 decision 2): the default path is index→select→fetch over the retrieval
    engine instead of dumping every note. Three scopes:

    - folder + slug (a chat continued ON a note): topic hydration — that
      node's full current content + its graph neighborhood labels, prepended,
      plus retrieval hits for the latest question. No transcript is ever
      loaded automatically (second-tier by decision).
    - folder only (the per-folder chat): UNCHANGED — context stays exactly
      that folder's entries; this scope's whole contract is that the answer
      can't come from somewhere it can't cite, so no global retrieval here.
    - no scope: retrieval hits for the latest question.

    Degradation (never a 500): retrieval uninitialized / empty / erroring
    falls back to the legacy behavior — the folder's entries when scoped,
    the old dump-everything context otherwise."""
    if not use_kb:
        return None

    if folder and not slug:
        intro = (
            f"You're chatting with the user about notes filed under \"{folder}\" specifically — "
            "not their whole knowledge base. Only the notes below exist for this conversation."
        )
        return f"{intro} {_GROUNDING_RULES}\n\n{_kb_context_for_folder(store, folder)}"

    topic = _topic_context(store, folder, slug) if folder and slug else None

    query = _last_user_text(messages)
    retrieved: str | None = None
    if query:
        try:
            retrieved = _kb_context(store, query, exclude_id=f"note:{folder}/{slug}" if topic else None)
        except Exception:
            retrieved = None  # uninitialized / empty / any retrieval error → legacy fallback

    if topic is not None:
        intro = (
            "You're continuing a conversation with the user about one topic from their "
            "personal knowledge base — its note's current state is below, with its "
            "connections. Anything else retrieved for their latest question follows it."
        )
        parts = [topic]
        if retrieved is not None:
            parts.append("## Retrieved for the latest question\n\n" + retrieved)
        elif folder:
            # Retrieval down: the topic note still hydrates; its folder's
            # entries stand in for retrieval (the legacy scoped behavior).
            parts.append(_kb_context_for_folder(store, folder))
        return f"{intro} {_GROUNDING_RULES}\n\n" + "\n\n".join(parts)

    intro = "You're chatting with the user about their own personal knowledge base."
    if retrieved is not None:
        intro += (
            " The entries below were retrieved for their latest question — a selection, "
            "not the whole knowledge base."
        )
        context = retrieved
    else:
        context = _kb_context_everything(store)
    return f"{intro} {_GROUNDING_RULES}\n\n{context}"


def _run_anthropic(model: str, messages: list[dict], kb_text: str | None) -> str:
    client = anthropic.Anthropic()
    # The KB gets re-sent as context on every turn of every chat — without
    # caching that's the full knowledge base billed at input-token price every
    # single message. cache_control lets Anthropic reuse that prefix (cache
    # hits are billed far below normal input price) while the KB is unchanged.
    system: list[dict] = []
    if kb_text:
        system.append({"type": "text", "text": kb_text, "cache_control": {"type": "ephemeral"}})
    system.append({"type": "text", "text": _PHOTO_INSTRUCTION})
    kwargs: dict = {
        "model": model,
        "max_tokens": 4096,
        "messages": messages,
        "system": system,
        # Server-side tool: Anthropic runs the search inside this one request.
        # Always on — the model only searches when a question needs fresh info.
        "tools": [{"type": _ANTHROPIC_SEARCH_TYPE[model], "name": "web_search", "max_uses": 5}],
    }
    if model in _ANTHROPIC_FALLBACK_MODELS:
        # Opus's safety classifiers can decline a request; this routes a
        # refusal to a fallback model server-side instead of failing the chat.
        response = client.beta.messages.create(
            betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs
        )
    else:
        response = client.messages.create(**kwargs)
    if response.stop_reason == "refusal":
        return "(the model declined to answer that one — try rephrasing, or pick a different model)"
    # With web_search enabled, content can interleave server_tool_use /
    # web_search_tool_result blocks with multiple text blocks (answer before
    # a search, more after) - join all of them, not just the first.
    return "\n\n".join(b.text for b in response.content if b.type == "text")


def _to_openai_input(messages: list[dict]) -> list[dict]:
    """Anthropic-shaped chat messages -> OpenAI Responses `input`. Text stays
    text; an attached image/PDF block becomes input_image/input_file (both
    carried as base64 data URLs). Assistant turns are text-only."""
    out: list[dict] = []
    for m in messages:
        content = m["content"]
        if isinstance(content, str):
            out.append({"role": m["role"], "content": content})
        elif m["role"] == "assistant":
            out.append({"role": "assistant", "content": "\n".join(b["text"] for b in content if b.get("type") == "text")})
        else:
            parts: list[dict] = []
            for b in content:
                if b["type"] == "text":
                    parts.append({"type": "input_text", "text": b["text"]})
                elif b["type"] == "image":
                    src = b["source"]
                    parts.append({"type": "input_image", "image_url": f"data:{src['media_type']};base64,{src['data']}"})
                elif b["type"] == "document":
                    src = b["source"]
                    parts.append(
                        {
                            "type": "input_file",
                            "filename": "document.pdf",
                            "file_data": f"data:{src['media_type']};base64,{src['data']}",
                        }
                    )
            out.append({"role": "user", "content": parts})
    return out


def _run_openai(model: str, messages: list[dict], kb_text: str | None) -> str:
    client = OpenAI()
    instructions = f"{kb_text}\n\n{_PHOTO_INSTRUCTION}" if kb_text else _PHOTO_INSTRUCTION
    kwargs: dict = {
        "model": model,
        "instructions": instructions,
        "input": _to_openai_input(messages),
        "tools": [{"type": "web_search"}],
        # The reasoning models spend this budget on hidden thinking too, so
        # it's generous; the -mini/-nano GPT-5s also get low reasoning effort
        # (chat doesn't need deep thought, and it's pure cost otherwise).
        "max_output_tokens": 8000,
    }
    if model.startswith("gpt-5"):
        kwargs["reasoning"] = {"effort": "low"}
    response = client.responses.create(**kwargs)
    return response.output_text or "(the model returned an empty reply)"


def bedrock_region() -> str:
    """QUINTACLE_BEDROCK_REGION wins (a knob just for this), then the standard
    AWS env vars, then us-east-1 — the region most Bedrock models launch in."""
    return (
        os.environ.get("QUINTACLE_BEDROCK_REGION")
        or os.environ.get("AWS_REGION")
        or os.environ.get("AWS_DEFAULT_REGION")
        or "us-east-1"
    )


def _to_converse_messages(messages: list[dict]) -> list[dict]:
    """Anthropic-shaped chat messages -> Bedrock Converse `messages`. Text
    stays text; attached image/PDF blocks (base64) become Converse bytes
    blocks. Assistant turns are text-only, same as the OpenAI conversion."""
    out: list[dict] = []
    for m in messages:
        content = m["content"]
        if isinstance(content, str):
            parts = [{"text": content}]
        elif m["role"] == "assistant":
            parts = [{"text": "\n".join(b["text"] for b in content if b.get("type") == "text")}]
        else:
            parts = []
            for b in content:
                if b["type"] == "text":
                    parts.append({"text": b["text"]})
                elif b["type"] == "image":
                    src = b["source"]
                    fmt = src["media_type"].split("/")[-1].replace("jpg", "jpeg")
                    parts.append({"image": {"format": fmt, "source": {"bytes": base64.b64decode(src["data"])}}})
                elif b["type"] == "document":
                    src = b["source"]
                    parts.append(
                        {"document": {"format": "pdf", "name": "document", "source": {"bytes": base64.b64decode(src["data"])}}}
                    )
        out.append({"role": m["role"], "content": parts})
    return out


def _run_bedrock_anthropic(raw_id: str, messages: list[dict], kb_text: str | None) -> str:
    """Claude-family Bedrock IDs go through the anthropic SDK's Bedrock client
    (same Messages shape as the direct API, AWS credentials/billing). No
    web_search tool here — server tools aren't a given on Bedrock deployments."""
    client = anthropic.AnthropicBedrockMantle(aws_region=bedrock_region())
    system: list[dict] = []
    if kb_text:
        system.append({"type": "text", "text": kb_text})
    system.append({"type": "text", "text": _PHOTO_INSTRUCTION})
    response = client.messages.create(model=raw_id, max_tokens=4096, messages=messages, system=system)
    if response.stop_reason == "refusal":
        return "(the model declined to answer that one — try rephrasing, or pick a different model)"
    return "\n\n".join(b.text for b in response.content if b.type == "text")


def _run_bedrock_converse(raw_id: str, messages: list[dict], kb_text: str | None) -> str:
    """Everything else on Bedrock (Nova, Llama, Mistral, any raw model ID the
    user types) goes through boto3's Converse API — one request shape that
    Bedrock translates for whatever model is behind the ID."""
    import boto3  # imported lazily: only the Bedrock path needs it

    client = boto3.client("bedrock-runtime", region_name=bedrock_region())
    system_text = f"{kb_text}\n\n{_PHOTO_INSTRUCTION}" if kb_text else _PHOTO_INSTRUCTION
    response = client.converse(
        modelId=raw_id,
        messages=_to_converse_messages(messages),
        system=[{"text": system_text}],
        inferenceConfig={"maxTokens": 4096},
    )
    parts = response["output"]["message"]["content"]
    reply = "\n\n".join(p["text"] for p in parts if "text" in p)
    return reply or "(the model returned an empty reply)"


def _run_bedrock(picker_id: str, messages: list[dict], kb_text: str | None) -> str:
    """Routes a `bedrock:<raw id>` picker value: Claude-family IDs use the
    anthropic SDK's Bedrock client, anything else the Converse API. AWS
    failures (no credentials, expired SSO, a bad model ID, no access in this
    region) come back as a readable BedrockError, never a stack trace."""
    import botocore.exceptions  # botocore ships with boto3; lazy like boto3 above

    raw_id = picker_id[len(BEDROCK_PREFIX):].strip() if picker_id.startswith(BEDROCK_PREFIX) else picker_id
    try:
        if "anthropic." in raw_id:
            return _run_bedrock_anthropic(raw_id, messages, kb_text)
        return _run_bedrock_converse(raw_id, messages, kb_text)
    except botocore.exceptions.ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        msg = e.response.get("Error", {}).get("Message", str(e))
        if code in ("ValidationException", "ResourceNotFoundException"):
            raise BedrockError(f"Bedrock rejected model \"{raw_id}\": {msg}") from e
        if code in ("AccessDeniedException", "UnrecognizedClientException", "ExpiredTokenException"):
            raise BedrockError(f"AWS access problem for \"{raw_id}\": {msg} — check your AWS credentials and model access in {bedrock_region()}") from e
        raise BedrockError(f"Bedrock error for \"{raw_id}\": {msg}") from e
    except botocore.exceptions.BotoCoreError as e:
        # NoCredentialsError, NoRegionError, expired SSO token retrieval, ...
        raise BedrockError(f"AWS credentials problem: {e} — configure AWS credentials (env vars or ~/.aws) to use Bedrock models") from e
    except anthropic.AnthropicError as e:
        raise BedrockError(f"Bedrock error for \"{raw_id}\": {e}") from e


def ollama_host() -> str:
    """QUINTACLE_OLLAMA_HOST wins (a knob just for this), then the standard
    OLLAMA_HOST, then Ollama's default localhost port. A bare host:port (the
    form OLLAMA_HOST is usually set to) gets an http:// scheme added."""
    host = os.environ.get("QUINTACLE_OLLAMA_HOST") or os.environ.get("OLLAMA_HOST") or "http://127.0.0.1:11434"
    if "://" not in host:
        host = "http://" + host
    return host.rstrip("/")


# Model-name fragments that mark an Ollama model as vision-capable — only
# these get image bytes passed through; everything else gets a placeholder
# (a text-only model given raw base64 would just hallucinate over noise).
_OLLAMA_VISION_HINTS = ("llava", "vision", "moondream", "minicpm-v", "gemma3", "qwen2.5vl", "qwen3-vl", "vl")


def _ollama_model_is_vision(raw_model: str) -> bool:
    name = raw_model.lower()
    return any(h in name for h in _OLLAMA_VISION_HINTS)


def _to_ollama_messages(messages: list[dict], vision: bool) -> list[dict]:
    """Anthropic-shaped chat messages -> Ollama chat `messages`. Text stays
    text; an attached image becomes Ollama's base64 `images` list when the
    model is vision-capable, a readable placeholder otherwise (same care as
    _to_converse_messages — never silently drop an attachment, and never feed
    raw base64 to a text model). PDFs always degrade to a placeholder: Ollama
    has no document input. Assistant turns are text-only, same as the
    OpenAI/Converse conversions."""
    out: list[dict] = []
    for m in messages:
        content = m["content"]
        if isinstance(content, str):
            out.append({"role": m["role"], "content": content})
            continue
        if m["role"] == "assistant":
            out.append({"role": "assistant", "content": "\n".join(b["text"] for b in content if b.get("type") == "text")})
            continue
        texts: list[str] = []
        images: list[str] = []
        for b in content:
            if b["type"] == "text":
                texts.append(b["text"])
            elif b["type"] == "image":
                if vision:
                    images.append(b["source"]["data"])
                else:
                    texts.append("[image omitted — local model can't see images]")
            elif b["type"] == "document":
                texts.append("[document omitted — local model can't read attached files]")
        msg: dict = {"role": "user", "content": "\n".join(texts)}
        if images:
            msg["images"] = images
        out.append(msg)
    return out


def _run_local(picker_id: str, messages: list[dict], kb_text: str | None) -> str:
    """Runs a `local:<model>` picker value against the Ollama daemon's HTTP
    API (non-streaming /api/chat) — stdlib urllib, no new dependency, no
    tokens billed. A down daemon or an un-pulled model comes back as a
    readable OllamaError, never a stack trace, mirroring _run_bedrock."""
    raw_model = picker_id[len(LOCAL_PREFIX):].strip() if picker_id.startswith(LOCAL_PREFIX) else picker_id
    host = ollama_host()
    system_text = f"{kb_text}\n\n{_PHOTO_INSTRUCTION}" if kb_text else _PHOTO_INSTRUCTION
    payload = {
        "model": raw_model,
        "messages": [{"role": "system", "content": system_text}] + _to_ollama_messages(messages, _ollama_model_is_vision(raw_model)),
        "stream": False,
        # Ollama's default context window is small (4k); the retrieved KB
        # block (up to ~24k chars ≈ 6-7k tokens) plus the conversation can
        # blow past 8k and get silently truncated — ask for 16k, same as
        # llm_dispatch's local parse path.
        "options": {"num_ctx": 16384},
    }
    req = urllib.request.Request(
        f"{host}/api/chat",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        # Generous timeout: a cold model load plus a long answer on CPU is slow.
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as e:
        try:
            msg = json.load(e).get("error", "")
        except Exception:
            msg = ""
        msg = msg or f"HTTP {e.code}"
        if "not found" in msg:
            raise OllamaError(f"Ollama doesn't have \"{raw_model}\": {msg} — pull it with `ollama pull {raw_model}`") from e
        raise OllamaError(f"Ollama error for \"{raw_model}\": {msg}") from e
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        reason = getattr(e, "reason", e)
        raise OllamaError(f"Ollama isn't reachable at {host} ({reason}) — start it with `ollama serve` to use local models") from e
    reply = (data.get("message") or {}).get("content", "")
    # Reasoning models (qwen3 et al.) put their thinking in a separate
    # `thinking` field, which we simply ignore — but older templates can leak
    # it inline as a <think> block, so strip that form too.
    reply = re.sub(r"^\s*<think>.*?</think>\s*", "", reply, flags=re.DOTALL)
    return reply.strip() or "(the model returned an empty reply)"


def run_kb_chat(
    store: KBStore,
    messages: list[dict],
    use_kb: bool,
    research: bool,
    folder: str | None = None,
    model: str | None = None,
    slug: str | None = None,
) -> str:
    entry = resolve_model(model, research)
    # Context is assembled once, identically for every provider — escalating
    # the same conversation to a cloud model transfers the SAME context.
    kb_text = _system_text(store, use_kb, folder, slug, messages)
    if entry["provider"] == "openai":
        reply = _run_openai(entry["id"], messages, kb_text)
    elif entry["provider"] == "bedrock":
        reply = _run_bedrock(entry["id"], messages, kb_text)
    elif entry["provider"] == "local":
        reply = _run_local(entry["id"], messages, kb_text)
    else:
        reply = _run_anthropic(entry["id"], messages, kb_text)
    return _resolve_photo_tags(reply)
