"""Provider-aware structured parsing — the ingest counterpart of chat.py's
model picker and drop.py's QUINTACLE_VISION switch.

Every easy text-parse seam (journal dumps, KB sorting, drop classification,
the structure_* extractors) routes its `anthropic.Anthropic().messages.parse`
call through parse_structured() here, which picks the backend per the decided
local-first routing (docs/local-inference-migration.md, "Decided 2026-10-15"):

  local   Ollama /api/chat with `format: <pydantic JSON schema>` — Ollama's
          schema-constrained generation on a small local model, no tokens
          billed. A down daemon, an un-pulled model, or local output that
          fails Pydantic validation raises a readable OllamaError.
  cloud   exactly the pre-existing metered Anthropic structured-parse call
          on DEFAULT_MODEL.
  auto    (the default) try local first; ANY local failure — daemon, model,
          or schema-invalid output — falls back to cloud with one warning
          log. Ingest never crashes because the local model fumbled.

Per-call `provider` (plumbed from the endpoints for the "redo with cloud"
step-back) wins over the QUINTACLE_INGEST_PROVIDER env default.

TEXT-ONLY in this wave: vision+schema sites (classify_image_type, receipt
extraction, the describe_* estimators) stay on cloud until the local
vision+schema path is proven — plain local vision descriptions are already
covered separately by QUINTACLE_VISION (see nodes/kb/drop.py). Geocoding
also deliberately stays cloud: resolving place names is world knowledge, a
poor fit for a small local model (documented exception).
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from contextvars import ContextVar
from dataclasses import dataclass

import anthropic
from pydantic import BaseModel, ValidationError

from .llm_config import DEFAULT_MODEL

# Shared with the chat's local provider — same daemon, same host resolution,
# same readable error type (imported, not duplicated; chat.py's behavior is
# untouched).
from .nodes.kb.chat import OllamaError, ollama_host

logger = logging.getLogger(__name__)

PROVIDER_ENV = "QUINTACLE_INGEST_PROVIDER"
LOCAL_PARSE_MODEL_ENV = "QUINTACLE_LOCAL_PARSE_MODEL"
# Parsing needs more model than chat-class narration — the 1.5B tier mangles
# multi-entry schemas; 8B is the proven desktop pick (see chat.py's curated
# local entries for the same class split).
DEFAULT_LOCAL_PARSE_MODEL = "qwen3:8b"

VALID_PROVIDERS = ("local", "cloud", "auto")


class LocalParseError(OllamaError):
    """Local model answered, but its output didn't validate against the
    requested schema — a *local* failure (feeds auto's cloud fallback),
    distinct from the daemon being unreachable."""


@dataclass
class ParseResult:
    """What parse_structured hands back: the validated model instance plus
    which backend actually served it — the endpoints surface provider_used
    so the frontend can offer "redo with cloud" only when local answered."""

    parsed: BaseModel
    provider_used: str  # "local" | "cloud"


def local_parse_model() -> str:
    return os.environ.get(LOCAL_PARSE_MODEL_ENV, "").strip() or DEFAULT_LOCAL_PARSE_MODEL


# --- per-request provider bookkeeping -------------------------------------
# One request (a /drop, a /journal parse) can make several parse_structured
# calls; the endpoint wants ONE answer for "who sorted this". A ContextVar
# collector keeps that per-request (each FastAPI request runs in its own
# context) without threading a mutable accumulator through every call site.

_collector: ContextVar[list[str] | None] = ContextVar("quintacle_providers_used", default=None)


def collect_providers() -> list[str]:
    """Installs and returns a fresh collector for the current request
    context — every parse_structured call after this appends the provider
    that actually served it."""
    used: list[str] = []
    _collector.set(used)
    return used


def summarize_providers(used: list[str]) -> str | None:
    """"local" / "cloud" when every routed call agreed, "mixed" otherwise
    (auto fell back mid-request), None when no routed call ran at all
    (fully deterministic handling)."""
    if not used:
        return None
    return used[0] if len(set(used)) == 1 else "mixed"


def _record(result: ParseResult) -> ParseResult:
    used = _collector.get()
    if used is not None:
        used.append(result.provider_used)
    return result


# --- the two backends ------------------------------------------------------


def _parse_cloud(system: str, user_content, output_format: type[BaseModel], max_tokens: int) -> BaseModel:
    """The pre-existing metered Anthropic structured-parse call, exactly as
    every nodes/*/llm.py site made it before this module existed."""
    client = anthropic.Anthropic()
    response = client.messages.parse(
        model=DEFAULT_MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user_content}],
        output_format=output_format,
    )
    return response.parsed_output


def _parse_local(system: str, user_content, output_format: type[BaseModel], max_tokens: int) -> BaseModel:
    """Ollama /api/chat with `format` set to the Pydantic model's JSON schema
    — the daemon constrains generation to the schema, we still validate the
    result through the real Pydantic model before trusting it. Same stdlib
    urllib + readable-error shape as chat._run_local."""
    raw_model = local_parse_model()
    host = ollama_host()
    payload = {
        "model": raw_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ],
        "stream": False,
        "format": output_format.model_json_schema(),
        # Parse payloads carry real context (meal/routine libraries, the KB
        # notes index) — bigger than chat's 8k default so nothing silently
        # truncates. num_predict mirrors the cloud call's max_tokens cap; a
        # truncated JSON tail fails validation below and (in auto) falls
        # back to cloud rather than committing a half-parsed result.
        "options": {"num_ctx": 16384, "num_predict": max_tokens},
        # Schema-constrained extraction doesn't want a thinking preamble —
        # verified live that Ollama accepts this for both thinking (qwen3)
        # and plain (qwen2.5) models.
        "think": False,
    }
    req = urllib.request.Request(
        f"{host}/api/chat",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        # Generous: a cold model load plus a long structured answer is slow.
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
        raise OllamaError(f"Ollama isn't reachable at {host} ({reason}) — start it with `ollama serve` to use local parsing") from e
    content = (data.get("message") or {}).get("content", "")
    try:
        return output_format.model_validate_json(content)
    except ValidationError as e:
        raise LocalParseError(
            f"local model \"{raw_model}\" returned output that doesn't match the "
            f"{output_format.__name__} schema: {e.error_count()} validation error(s) — "
            "retry, pick a bigger QUINTACLE_LOCAL_PARSE_MODEL, or redo with cloud"
        ) from e


# --- the dispatch -----------------------------------------------------------


def parse_structured(
    system: str,
    user_content,
    output_format: type[BaseModel],
    *,
    provider: str | None = None,
    max_tokens: int = 4096,
) -> ParseResult:
    """One structured parse, routed per the local-first rule. `provider`
    (from an endpoint's ?provider=... step-back redo) wins; otherwise the
    QUINTACLE_INGEST_PROVIDER env var; default "auto" (local first, cloud
    fallback). Returns the validated instance plus which provider served."""
    mode = (provider or os.environ.get(PROVIDER_ENV) or "auto").strip().lower() or "auto"
    if mode not in VALID_PROVIDERS:
        raise ValueError(f"unknown ingest provider {mode!r} — use one of {', '.join(VALID_PROVIDERS)}")
    if mode in ("local", "auto"):
        try:
            return _record(ParseResult(_parse_local(system, user_content, output_format, max_tokens), "local"))
        except OllamaError as e:
            if mode == "local":
                raise
            logger.warning(
                "ingest provider auto: local parse (%s) failed, falling back to cloud (%s): %s",
                local_parse_model(),
                DEFAULT_MODEL,
                e,
            )
    return _record(ParseResult(_parse_cloud(system, user_content, output_format, max_tokens), "cloud"))
