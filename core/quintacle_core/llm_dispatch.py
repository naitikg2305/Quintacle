"""Provider-aware structured parsing — the ingest counterpart of chat.py's
model picker and drop.py's QUINTACLE_VISION switch.

Every easy text-parse seam (journal dumps, KB sorting, drop classification,
the structure_* extractors) routes its `anthropic.Anthropic().messages.parse` (now `max_backend.cloud_client()`, 2026-11-05)
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

[2026-11-19 owner decision, "cant auto switch to cloud": auto NO LONGER
falls back to cloud. Cloud is only ever a user-chosen escalation (the "Redo
with cloud" step-back re-sends the ORIGINAL input with provider=cloud). In
auto, a local failure of any kind — daemon down / not installed, model not
pulled, schema-invalid output — now raises the local error (OllamaError /
LocalParseError) exactly like provider=local; endpoints surface it as a
readable error (/drop answers with `local_unavailable` so the review UI
offers Redo with cloud). "auto" stays a valid value (env/old clients send
it) and now behaves as local. Explicit provider="cloud" is unchanged. The
auto description above is kept as decision history.]

TEXT-ONLY in this wave: vision+schema sites (classify_image_type, receipt
extraction, the describe_* estimators) stay on cloud until the local
vision+schema path is proven — plain local vision descriptions are already
covered separately by QUINTACLE_VISION (see nodes/kb/drop.py).
[2026-11-06 status: superseded for images — every vision site now routes
through perception/image_policy.py (QUINTACLE_IMAGE_PROVIDER, default
local): OCR + deterministic parsers first, then THIS module's local text
parse over the OCR text, then the local VLM. The note above is kept as the
decision history.] Geocoding
also deliberately stays cloud: resolving place names is world knowledge, a
poor fit for a small local model (documented exception).
[2026-11-11 correction: geocoding no longer stays cloud. It is local-first
now — photo_organizer.geocode answers from the offline GeoNames gazetteer
(geo_offline.py) under the image policy, and calls Claude only when the
provider is auto/cloud. The legacy QUINTACLE_VISION switch named in the
first line is likewise retired as a source of truth: describe_images goes
through image_policy.image_provider(), which maps the legacy var with a
deprecation warning. Text above kept as decision history.]
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
from .max_backend import cloud_client

logger = logging.getLogger(__name__)

PROVIDER_ENV = "QUINTACLE_INGEST_PROVIDER"
LOCAL_PARSE_MODEL_ENV = "QUINTACLE_LOCAL_PARSE_MODEL"
# Parsing needs more model than chat-class narration — the 1.5B tier mangles
# multi-entry schemas; 8B is the proven desktop pick (see chat.py's curated
# local entries for the same class split).
DEFAULT_LOCAL_PARSE_MODEL = "qwen3:8b"

# 2026-11-11, measured on the 12 GB GPU: qwen3:8b takes 6.4 GB at 8k and
# 7.5 GB at 16k; qwen2.5vl takes up to 4.4 GB. At 16k the two don't fit
# together, so a photo drop swapped models. The largest real drop measured
# ~4.9k tokens, so parsing runs at 8k and steps up to 16k only for a request
# that needs it. Each size change reloads the model (~3 s measured), so the
# size is fixed per bucket, never computed exactly.
PARSE_NUM_CTX = 8192
PARSE_NUM_CTX_LARGE = 16384


def parse_num_ctx(system: str, user_content: str, max_tokens: int) -> int:
    """8k unless this request's prompt (estimated conservatively at 3 chars
    per token) plus its output cap plus a margin won't fit."""
    need = (len(system) + len(user_content)) // 3 + max_tokens + 512
    return PARSE_NUM_CTX if need <= PARSE_NUM_CTX else PARSE_NUM_CTX_LARGE

VALID_PROVIDERS = ("local", "cloud", "auto")
PARSE_SEED = 42


class LocalParseError(OllamaError):
    """Local model answered, but its output didn't validate against the
    requested schema — a *local* failure, distinct from the daemon being
    unreachable. (Until 2026-11-19 it fed auto's cloud fallback; now it is
    raised to the caller in auto too — cloud only by user choice.)"""


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
    record_provider(result.provider_used)
    return result


def record_provider(provider_used: str) -> None:
    """Append one served-by to the current request's collector. Public since
    2026-11-06 so the local-first IMAGE pipeline (perception/image_policy.py)
    reports into the same provider_used the Redo-with-cloud UI keys off."""
    used = _collector.get()
    if used is not None:
        used.append(provider_used)


# --- the two backends ------------------------------------------------------


def _parse_cloud(system: str, user_content, output_format: type[BaseModel], max_tokens: int) -> BaseModel:
    """The pre-existing metered Anthropic structured-parse call, exactly as
    every nodes/*/llm.py site made it before this module existed."""
    client = cloud_client()
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
        # notes index) — sized per request by parse_num_ctx (8k, 16k only
        # when this request needs it) so nothing silently truncates. num_predict mirrors the cloud call's max_tokens cap; a
        # truncated JSON tail fails validation below and raises (never a
        # half-parsed result; since 2026-11-19 never a silent cloud retry).
        # 2026-11-07: temperature 0 + a fixed seed — structured parsing (and
        # the USDA candidate pick, which routes through here) must give the
        # same answer for the same input; chat generation is untouched.
        "options": {"num_ctx": parse_num_ctx(system, user_content, max_tokens), "num_predict": max_tokens, "temperature": 0, "seed": PARSE_SEED},
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
        if data.get("done_reason") == "length":
            # 2026-11-19 (owner fix 5, diagnosed): the model looped until the token cap -> cut-off JSON.
            raise LocalParseError(
                f"local model \"{raw_model}\" ran out of tokens ({max_tokens}) before finishing the "
                f"{output_format.__name__} (it was repeating itself) — redo with cloud"
            ) from e
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
    QUINTACLE_INGEST_PROVIDER env var; default "auto". Returns the validated
    instance plus which provider served.

    2026-11-19 (owner): "auto" never switches to cloud on its own — it runs
    local and a local failure raises (OllamaError / LocalParseError). Only an
    explicit provider="cloud" (the user's Redo with cloud) reaches the cloud."""
    mode = (provider or os.environ.get(PROVIDER_ENV) or "auto").strip().lower() or "auto"
    if mode not in VALID_PROVIDERS:
        raise ValueError(f"unknown ingest provider {mode!r} — use one of {', '.join(VALID_PROVIDERS)}")
    if mode == "cloud":
        return _record(ParseResult(_parse_cloud(system, user_content, output_format, max_tokens), "cloud"))
    # local and auto: local only. A failure propagates — no cloud call the
    # user didn't choose.
    return _record(ParseResult(_parse_local(system, user_content, output_format, max_tokens), "local"))
