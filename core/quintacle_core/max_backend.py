"""Claude through headless Claude Code (`claude -p`), billed to the logged-in
Claude Max subscription instead of the metered API (owner decision
2026-11-05; ported from TailorCV's `llm/claude_code.py`).

How it's used: every cloud call site in Quintacle gets its client from
`cloud_client()` instead of `anthropic.Anthropic()`. The returned object
speaks the same `messages.parse(...)` / `messages.create(...)` shape the call
sites already use, so each site's change is one line. Per call it tries Max
first and falls back to the real Anthropic API (key from `.env`) on ANY Max
failure — CLI missing (the phone/Termux case), not logged in, usage limit
hit, timeout, bad output — logging one warning. Nothing crashes because Max
isn't there.

Mode switch (env `QUINTACLE_CLOUD`):
  max   (default) Max first, API fallback.
  api   API only — the pre-2026-11-05 behaviour.
`QUINTACLE_DISABLE_MAX=1` is the same as `api` (tests set it so they never
spend subscription usage). `QUINTACLE_CLAUDE_BIN` overrides the CLI path.

Each call: one stateless turn, no tools (chat's web search is the exception,
see `run`), no MCP servers, no user/project settings (so no hooks fire —
the work-log Stop hook would otherwise write a stub per call), no saved
session. ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN are stripped from the
child's env, or the CLI would bill the API instead of the subscription.
Input goes in as stream-json, which accepts the same content blocks the API
does (text, base64 images — verified live), so vision calls work unchanged.
The CLI has no max_tokens/temperature flags; prompts already ask for short
output. Privacy is unaffected: Max is a cloud model, so every private-note
rule for cloud applies (privacy.py) — the callers already filter.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
from typing import Any

logger = logging.getLogger(__name__)

CLOUD_ENV = "QUINTACLE_CLOUD"
DISABLE_ENV = "QUINTACLE_DISABLE_MAX"
BIN_ENV = "QUINTACLE_CLAUDE_BIN"
TIMEOUT_ENV = "QUINTACLE_MAX_TIMEOUT"


class MaxError(RuntimeError):
    """A readable Max failure (CLI missing, not logged in, limit hit,
    timeout, unusable output). Callers fall back to the API on it."""


def enabled() -> bool:
    if os.environ.get(DISABLE_ENV):
        return False
    return (os.environ.get(CLOUD_ENV) or "max").strip().lower() != "api"


def binary() -> str:
    return os.environ.get(BIN_ENV) or "claude"


def available() -> bool:
    """Max is usable on this machine: enabled and the CLI is on PATH. On the
    phone (Termux) the CLI is normally absent, so this is False and every
    cloud call goes straight to the API."""
    return enabled() and shutil.which(binary()) is not None


def alias_for(model: str | None) -> str:
    """API model id -> Claude Code alias. The CLI resolves an alias to the
    newest model of that tier, so `claude-haiku-4-5` becomes the current
    Haiku on Max (fine: the subscription doesn't bill per model)."""
    m = (model or "").lower()
    for tier in ("opus", "sonnet", "haiku"):
        if tier in m:
            return tier
    return "haiku"


def _system_text(system: Any) -> str:
    """API `system` may be a string or a list of text blocks (cache_control
    etc.) — the CLI wants one string."""
    if not system:
        return ""
    if isinstance(system, str):
        return system
    return "\n\n".join(b.get("text", "") for b in system if isinstance(b, dict) and b.get("type") == "text")


def _flatten_messages(messages: list[dict]) -> list[dict] | str:
    """The CLI's stream-json input takes user turns only. A single user turn
    passes through as-is (content blocks and all — images survive). A
    multi-turn history is rendered into one user turn as a transcript, with
    any non-text blocks of the LAST user turn kept as real blocks."""
    if len(messages) == 1 and messages[0].get("role") == "user":
        c = messages[0].get("content")
        return c if isinstance(c, list) else str(c or "")

    def text_of(content: Any) -> str:
        if isinstance(content, str):
            return content
        return "\n".join(b.get("text", "") for b in content or [] if isinstance(b, dict) and b.get("type") == "text")

    *history, last = messages
    lines = ["Conversation so far:"]
    for m in history:
        who = "User" if m.get("role") == "user" else "Assistant"
        lines.append(f"{who}: {text_of(m.get('content'))}")
    lines.append("\nNow reply to the user's latest message:")
    last_content = last.get("content")
    blocks = [b for b in (last_content if isinstance(last_content, list) else []) if isinstance(b, dict) and b.get("type") != "text"]
    return [*blocks, {"type": "text", "text": "\n".join(lines) + "\n" + text_of(last_content)}]


def run(
    system: Any,
    messages: list[dict],
    *,
    model: str | None = None,
    json_schema: dict | None = None,
    tools: tuple[str, ...] = (),
    timeout: float | None = None,
) -> dict:
    """One headless call. Returns {"text", "structured", "model"}. Raises
    MaxError on any failure. `tools` (e.g. ("WebSearch", "WebFetch") for chat)
    are the only tools that exist and are pre-approved so the headless run
    never stops for permission."""
    if not available():
        raise MaxError("Claude Max isn't available here (CLI not found or Max disabled)")
    content = _flatten_messages(messages)
    msg = {"type": "user", "message": {"role": "user", "content": content}}
    tool_args = ["--tools", ",".join(tools), "--allowedTools", *tools] if tools else ["--tools", ""]
    cmd = [
        binary(), "-p",
        "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
        "--model", alias_for(model),
        "--system-prompt", _system_text(system) or "You are a helpful assistant.",
        *tool_args,
        "--strict-mcp-config", "--setting-sources", "", "--no-session-persistence",
    ]
    if json_schema is not None:
        cmd += ["--json-schema", json.dumps(json_schema)]
    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
    limit = timeout or float(os.environ.get(TIMEOUT_ENV) or (600 if tools else 240))
    try:
        p = subprocess.run(
            cmd, input=json.dumps(msg) + "\n", capture_output=True, text=True,
            timeout=limit, env=env, cwd=tempfile.gettempdir(),
        )
    except subprocess.TimeoutExpired as e:
        raise MaxError(f"Claude Max timed out after {limit:.0f}s") from e
    except OSError as e:
        raise MaxError(f"Claude Max couldn't start: {e}") from e
    result = None
    for line in p.stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "result":
            result = event
    if result is None:
        raise MaxError(f"Claude Max returned no result (exit {p.returncode}): {(p.stderr or p.stdout)[:200]!r}")
    if result.get("is_error") or result.get("subtype") != "success":
        raise MaxError(f"Claude Max failed: {str(result.get('result') or result.get('subtype'))[:200]}")
    if json_schema is not None and result.get("structured_output") is None:
        raise MaxError("Claude Max returned no structured output")
    return {
        "text": result.get("result") or "",
        "structured": result.get("structured_output"),
        "model": next(iter(result.get("modelUsage") or {}), alias_for(model)),
    }


# JSON-Schema keywords Pydantic emits that aren't standard JSON Schema — the
# CLI validates --json-schema strictly and rejects them ("discriminator" on
# tagged unions, seen live 2026-11-05). Dropping them only loosens the
# constraint; the answer is still validated by the real Pydantic model.
_NON_STANDARD = {"discriminator"}


def clean_schema(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: clean_schema(v) for k, v in node.items() if k not in _NON_STANDARD}
    if isinstance(node, list):
        return [clean_schema(v) for v in node]
    return node


# --- the Anthropic-client look-alike ------------------------------------------


def _text_response(text: str) -> SimpleNamespace:
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        stop_reason="end_turn",
        parsed_output=None,
    )


class _Messages:
    def __init__(self, owner: "CloudClient"):
        self._owner = owner

    def parse(self, *, model=None, max_tokens=None, system=None, messages, output_format, **kw):
        if available():
            try:
                out = run(system, messages, model=model, json_schema=clean_schema(output_format.model_json_schema()))
                parsed = output_format.model_validate(out["structured"])
                return SimpleNamespace(parsed_output=parsed, content=[], stop_reason="end_turn")
            except Exception as e:  # MaxError, pydantic ValidationError, anything — fall back
                logger.warning("Claude Max parse failed, falling back to the API: %s", e)
        kwargs = {"model": model, "max_tokens": max_tokens, "messages": messages, "output_format": output_format, **kw}
        if system is not None:
            kwargs["system"] = system
        return self._owner._api().messages.parse(**kwargs)

    def create(self, *, model=None, max_tokens=None, system=None, messages, **kw):
        if available() and not kw.get("tools"):
            try:
                return _text_response(run(system, messages, model=model)["text"])
            except Exception as e:
                logger.warning("Claude Max call failed, falling back to the API: %s", e)
        kwargs = {"model": model, "max_tokens": max_tokens, "messages": messages, **kw}
        if system is not None:
            kwargs["system"] = system
        return self._owner._api().messages.create(**kwargs)


class CloudClient:
    """Drop-in for `anthropic.Anthropic()` at the call sites: Max first, API
    fallback. The real client is only constructed if the fallback runs."""

    def __init__(self):
        self.messages = _Messages(self)
        self._client = None

    def _api(self):
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic()
        return self._client


def cloud_client() -> CloudClient:
    return CloudClient()
