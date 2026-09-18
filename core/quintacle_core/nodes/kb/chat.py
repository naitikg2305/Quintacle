from __future__ import annotations

import json
import re
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


def _kb_context(store: KBStore) -> str:
    sections = []
    for folder in store.list_folders():
        for slug in store.list_entries(folder):
            content = store.read(folder, slug)
            if content:
                sections.append(_render_entry(store, folder, slug, content))
    return "\n\n".join(sections) if sections else "(the knowledge base is empty right now)"


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
# (its own web_search tool). Both take the same Anthropic-shaped message list
# from the frontend — the OpenAI path converts it (see _to_openai_input).
# `price` is $/1M tokens in/out, shown in the dropdown so the cost is visible.
CHAT_MODELS: list[dict] = [
    {"id": "claude-haiku-4-5", "label": "Claude Haiku 4.5", "provider": "anthropic", "price": "$1 / $5"},
    {"id": "claude-sonnet-5", "label": "Claude Sonnet 5", "provider": "anthropic", "price": "$2 / $10"},
    {"id": "claude-opus-5", "label": "Claude Opus 5", "provider": "anthropic", "price": "$5 / $25"},
    {"id": "gpt-4o-mini", "label": "GPT-4o mini", "provider": "openai", "price": "$0.15 / $0.60"},
    {"id": "gpt-5-nano", "label": "GPT-5 nano", "provider": "openai", "price": "$0.05 / $0.40"},
    {"id": "gpt-5-mini", "label": "GPT-5 mini", "provider": "openai", "price": "$0.25 / $2"},
]
_MODELS_BY_ID = {m["id"]: m for m in CHAT_MODELS}

# The dynamic-filtering search variant needs Sonnet 5+; Haiku takes the basic one.
_ANTHROPIC_SEARCH_TYPE = {
    "claude-haiku-4-5": "web_search_20250305",
    "claude-sonnet-5": "web_search_20260209",
    "claude-opus-5": "web_search_20260209",
}


class UnknownModelError(ValueError):
    pass


def resolve_model(model: str | None, research: bool) -> dict:
    """`model` (from the dropdown) wins; otherwise fall back to the old
    research flag so callers that never learned about the picker (the folder
    chat, the read-only chat) keep working on the same defaults as before."""
    wanted = model or (RESEARCH_MODEL if research else DEFAULT_MODEL)
    entry = _MODELS_BY_ID.get(wanted)
    if entry is None:
        raise UnknownModelError(f"unknown chat model: {wanted}")
    return entry


def _system_text(store: KBStore, use_kb: bool, folder: str | None) -> str | None:
    """The KB-grounding block, or None when the KB is switched off."""
    if not use_kb:
        return None
    intro = (
        f"You're chatting with the user about notes filed under \"{folder}\" specifically — "
        "not their whole knowledge base. Only the notes below exist for this conversation."
        if folder
        else "You're chatting with the user about their own personal knowledge base."
    )
    context = _kb_context_for_folder(store, folder) if folder else _kb_context(store)
    return (
        f"{intro} Ground your answers in the notes below when relevant — reference "
        "them naturally, don't just recite them back. If something isn't covered in "
        "the notes, say so plainly instead of guessing. This chat is a scratchpad for "
        "thinking out loud — nothing here is saved automatically; the user pushes "
        "anything worth keeping into the knowledge base separately.\n\n" + context
    )


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
    if model == "claude-opus-5":
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


def run_kb_chat(
    store: KBStore,
    messages: list[dict],
    use_kb: bool,
    research: bool,
    folder: str | None = None,
    model: str | None = None,
) -> str:
    entry = resolve_model(model, research)
    kb_text = _system_text(store, use_kb, folder)
    if entry["provider"] == "openai":
        reply = _run_openai(entry["id"], messages, kb_text)
    else:
        reply = _run_anthropic(entry["id"], messages, kb_text)
    return _resolve_photo_tags(reply)
