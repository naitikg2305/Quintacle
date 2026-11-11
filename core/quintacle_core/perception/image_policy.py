"""Who is allowed to look at an image — the local-first routing policy for
every image-understanding call (2026-11-06).

Before this, every photo classification / receipt / nutrition-label /
describe_* call went straight to the cloud. The owner's decision: "it should
always have been local". QUINTACLE_IMAGE_PROVIDER (read per call):

  local  (default)  never call the cloud automatically. The local stack —
                    OCR + deterministic parsers, YOLO tags, the local text
                    model over OCR TEXT, the local VLM — answers, or the call
                    raises LocalImageUnavailable: "couldn't read locally —
                    Redo with cloud?". The Redo-with-cloud button re-sends
                    the ORIGINAL image with provider=cloud (a step back,
                    never a re-prompt over local output).
  auto              local first; any local failure falls back to cloud with
                    one warning log (roughly the old behavior, but local
                    gets first shot).
  cloud             the pre-existing cloud vision calls, unchanged.

A per-request override (/drop's `provider` form field) wins over the env
var, via a ContextVar so the deeply-nested call sites (describe_drop ->
_describe_image -> describe_images) inherit it without threading a
parameter through every signature. Private content is pinned to local
regardless of either.

Each run also records WHICH pipeline served it — "ocr+parser",
"ocr+local-llm", "yolo+local-vlm", "yolo" (tags only), or "cloud" — so
proposals can carry a small "read locally" badge, and feeds
llm_dispatch's provider collector so the existing provider_used /
Redo-with-cloud UI sees image calls too.

Legacy QUINTACLE_VISION (describe_images' old local/auto/cloud switch) is
still honored when explicitly set — see nodes/kb/drop.describe_images.
[2026-11-11 correction: describe_images no longer reads QUINTACLE_VISION
itself — it was a second source of truth, and QUINTACLE_VISION=cloud left on
a machine silently made image description default to cloud. image_provider()
below is now the ONLY place the legacy var is read: when set (and
QUINTACLE_IMAGE_PROVIDER isn't), it logs a one-time deprecation warning and
maps local->local, auto->auto, cloud->auto. cloud deliberately maps to auto
(local first, cloud only as fallback) so local stays the default; forcing
cloud now takes QUINTACLE_IMAGE_PROVIDER=cloud or a per-request Redo.]
"""

from __future__ import annotations

import logging
import os
from contextvars import ContextVar
from typing import Callable, TypeVar

logger = logging.getLogger(__name__)

IMAGE_PROVIDER_ENV = "QUINTACLE_IMAGE_PROVIDER"
LEGACY_VISION_ENV = "QUINTACLE_VISION"
# Legacy QUINTACLE_VISION value -> image provider. cloud -> auto on purpose:
# a stale legacy setting may widen to a cloud FALLBACK, never to cloud-first.
_LEGACY_VISION_MAP = {"local": "local", "auto": "auto", "cloud": "auto"}
VALID_IMAGE_PROVIDERS = ("local", "auto", "cloud")
DEFAULT_IMAGE_PROVIDER = "local"

PIPELINES = ("ocr+parser", "ocr+local-llm", "yolo+local-vlm", "yolo", "cloud")

T = TypeVar("T")


class LocalImageUnavailable(RuntimeError):
    """The local image stack couldn't produce a result and the policy
    forbids silently using the cloud. Subclasses RuntimeError so the old
    QUINTACLE_VISION=local contract ("raises RuntimeError") still holds."""

    def __init__(self, message: str, *, what: str = "image"):
        super().__init__(message)
        self.what = what


_request_provider: ContextVar[str | None] = ContextVar("quintacle_image_provider", default=None)
_pipelines: ContextVar[list[str] | None] = ContextVar("quintacle_image_pipelines", default=None)


def set_request_provider(provider: str | None) -> None:
    """Pin this request context's image provider (None = no override)."""
    _request_provider.set((provider or "").strip().lower() or None)


def request_override() -> str | None:
    """This request's pinned image provider, if any (Redo with cloud)."""
    return _request_provider.get()


_legacy_warned = False


def _legacy_vision_mode() -> str | None:
    """The mapped legacy QUINTACLE_VISION value, or None when unset. Warns
    once per process (deprecation); an unknown value is ignored (local)."""
    global _legacy_warned
    raw = (os.environ.get(LEGACY_VISION_ENV) or "").strip().lower()
    if not raw:
        return None
    mapped = _LEGACY_VISION_MAP.get(raw)
    if not _legacy_warned:
        _legacy_warned = True
        logger.warning(
            "%s=%r is deprecated — use %s (local|auto|cloud). Mapped to %r%s.",
            LEGACY_VISION_ENV,
            raw,
            IMAGE_PROVIDER_ENV,
            mapped or DEFAULT_IMAGE_PROVIDER,
            " (cloud is now only a fallback; set QUINTACLE_IMAGE_PROVIDER=cloud to force it)" if raw == "cloud" else "",
        )
    return mapped


def image_provider(provider: str | None = None, *, private: bool = False) -> str:
    """explicit arg > request override > QUINTACLE_IMAGE_PROVIDER > legacy
    QUINTACLE_VISION (mapped, deprecated; 2026-11-11) > local.
    `private` pins local no matter what."""
    if private:
        return "local"
    mode = (
        provider
        or _request_provider.get()
        or os.environ.get(IMAGE_PROVIDER_ENV)
        or _legacy_vision_mode()
        or DEFAULT_IMAGE_PROVIDER
    ).strip().lower()
    if mode not in VALID_IMAGE_PROVIDERS:
        raise ValueError(f"unknown image provider {mode!r} — use one of {', '.join(VALID_IMAGE_PROVIDERS)}")
    return mode


def text_provider_for_image(provider: str | None = None, *, private: bool = False) -> str:
    """The ingest provider for a TEXT-model call over image-derived text (OCR
    output, a local VLM caption). Mirrors the image policy so local=never
    cloud stays true one step downstream too."""
    return image_provider(provider, private=private)


# ----------------------------------------------------------- bookkeeping


def collect_pipelines() -> list[str]:
    used: list[str] = []
    _pipelines.set(used)
    return used


def record_pipeline(pipeline: str) -> None:
    used = _pipelines.get()
    if used is not None:
        used.append(pipeline)
    try:
        from .. import llm_dispatch

        llm_dispatch.record_provider("cloud" if pipeline == "cloud" else "local")
    except Exception:  # bookkeeping must never fail a request
        pass


def summarize_pipeline(used: list[str]) -> str | None:
    """'cloud' if any step went to cloud; else the last (= the extraction
    step, which is what the badge describes); None when no image step ran."""
    if not used:
        return None
    if "cloud" in used:
        return "cloud"
    return used[-1]


# --------------------------------------------------------------- dispatch


def run_image_task(
    local_fn: Callable[[], tuple[T, str | None] | None],
    cloud_fn: Callable[[], T],
    *,
    what: str = "image",
    provider: str | None = None,
    private: bool = False,
) -> T:
    """The one policy gate. `local_fn` returns (result, pipeline) or None
    (couldn't do it), or raises LocalImageUnavailable with a reason.
    `cloud_fn` is the pre-existing cloud call. A pipeline of None means the
    step was a routing decision, not an extraction — not badge-worthy."""
    mode = image_provider(provider, private=private)
    if mode == "cloud":
        result = cloud_fn()
        record_pipeline("cloud")
        return result
    reason = "the local OCR/vision stack returned nothing"
    try:
        out = local_fn()
    except LocalImageUnavailable as exc:
        out, reason = None, str(exc)
    except Exception as exc:  # a local model/daemon failure is a local failure, never a crash in auto
        from ..nodes.kb.chat import OllamaError

        if not isinstance(exc, OllamaError):
            raise
        out, reason = None, str(exc)
    if out is not None:
        result, pipeline = out
        if pipeline:
            record_pipeline(pipeline)
        else:
            try:
                from .. import llm_dispatch

                llm_dispatch.record_provider("local")
            except Exception:
                pass
        return result
    if mode == "auto" and not private:
        logger.warning("image provider auto: couldn't read this %s locally (%s) — falling back to cloud", what, reason)
        result = cloud_fn()
        record_pipeline("cloud")
        return result
    raise LocalImageUnavailable(
        f"couldn't read this {what} locally ({reason})" + ("" if private else " — Redo with cloud?"),
        what=what,
    )


__all__ = [
    "DEFAULT_IMAGE_PROVIDER",
    "IMAGE_PROVIDER_ENV",
    "LocalImageUnavailable",
    "PIPELINES",
    "VALID_IMAGE_PROVIDERS",
    "collect_pipelines",
    "image_provider",
    "record_pipeline",
    "run_image_task",
    "set_request_provider",
    "summarize_pipeline",
    "text_provider_for_image",
]
