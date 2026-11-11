"""2026-11-11 local-first fixes from the model-coverage audit
(docs/testing/model-coverage-2026-11-11.md, "Cloud-only paths"):

1. auto_journal.maybe_polish goes through llm_dispatch.parse_structured
   pinned to provider="local" — never a direct cloud call; any failure
   keeps the deterministic line.
2. image_policy.image_provider() is the single source of truth for the
   image provider; the legacy QUINTACLE_VISION var is mapped there with a
   one-time deprecation warning, and legacy `cloud` maps to `auto` so local
   stays first.

All FAKED: parse_structured / the local + cloud vision edges are stubbed."""
from __future__ import annotations

import pytest

import quintacle_core.local_vlm as local_vlm
from quintacle_core import llm_dispatch
from quintacle_core.nodes.kb import auto_journal, drop
from quintacle_core.nodes.kb.chat import OllamaError
from quintacle_core.perception import image_policy

LINE = "📷 2:14 PM — with Alex at Hermann Park · sunny"
PHOTOS = [(b"jpeg-bytes", "image/jpeg")]


# ------------------------------------------------------------- fix 1: polish


@pytest.fixture
def polish_on(monkeypatch):
    monkeypatch.setenv(auto_journal.POLISH_ENV, "1")
    monkeypatch.delenv(auto_journal.POLISH_PROVIDER_ENV, raising=False)


def _fake_parse(answer: str, seen: dict):
    def fake(system, user_content, output_format, *, provider=None, max_tokens=4096):
        seen.update(system=system, user=user_content, provider=provider, fmt=output_format)
        return llm_dispatch.ParseResult(output_format(sentence=answer), "local")

    return fake


def test_polish_off_by_default_makes_no_model_call(monkeypatch):
    monkeypatch.delenv(auto_journal.POLISH_ENV, raising=False)

    def boom(*a, **k):
        raise AssertionError("no model call when polish is off")

    monkeypatch.setattr(llm_dispatch, "parse_structured", boom)
    assert auto_journal.maybe_polish(LINE) == LINE


def test_polish_routes_through_dispatch_pinned_local(monkeypatch, polish_on):
    seen: dict = {}
    monkeypatch.setattr(llm_dispatch, "parse_structured", _fake_parse("📷 At 2:14 PM I was with Alex at Hermann Park, sunny.", seen))

    assert auto_journal.maybe_polish(LINE) == "📷 At 2:14 PM I was with Alex at Hermann Park, sunny."
    assert seen["provider"] == "local"
    assert seen["user"] == LINE
    assert "Keep every fact" in seen["system"]


def test_polish_never_reaches_cloud_by_default(monkeypatch, polish_on):
    # Real dispatch, local backend down: provider=local must raise (caught),
    # never fall back to the cloud parse.
    def local_down(*a, **k):
        raise OllamaError("daemon down")

    def cloud_must_not_run(*a, **k):
        raise AssertionError("polish must not call the cloud by default")

    monkeypatch.setattr(llm_dispatch, "_parse_local", local_down)
    monkeypatch.setattr(llm_dispatch, "_parse_cloud", cloud_must_not_run)

    assert auto_journal.maybe_polish(LINE) == LINE


def test_polish_cloud_only_when_user_opts_in(monkeypatch, polish_on):
    monkeypatch.setenv(auto_journal.POLISH_PROVIDER_ENV, "cloud")
    seen: dict = {}
    monkeypatch.setattr(llm_dispatch, "parse_structured", _fake_parse("polished", seen))

    assert auto_journal.maybe_polish(LINE) == "polished"
    assert seen["provider"] == "cloud"


@pytest.mark.parametrize("answer", ["", "   "])
def test_polish_empty_answer_keeps_deterministic_line(monkeypatch, polish_on, answer):
    monkeypatch.setattr(llm_dispatch, "parse_structured", _fake_parse(answer, {}))
    assert auto_journal.maybe_polish(LINE) == LINE


def test_polish_any_failure_keeps_deterministic_line(monkeypatch, polish_on):
    def boom(*a, **k):
        raise RuntimeError("anything")

    monkeypatch.setattr(llm_dispatch, "parse_structured", boom)
    assert auto_journal.maybe_polish(LINE) == LINE


# ------------------------------------------------- fix 2: legacy QUINTACLE_VISION


@pytest.fixture
def clean_policy(monkeypatch):
    monkeypatch.delenv("QUINTACLE_IMAGE_PROVIDER", raising=False)
    monkeypatch.delenv("QUINTACLE_VISION", raising=False)
    monkeypatch.setattr(image_policy, "_legacy_warned", False)
    image_policy.set_request_provider(None)
    yield
    image_policy.set_request_provider(None)


@pytest.mark.parametrize("legacy,expected", [("local", "local"), ("auto", "auto"), ("cloud", "auto"), ("CLOUD ", "auto"), ("bogus", "local")])
def test_legacy_vision_maps_in_image_policy(monkeypatch, clean_policy, legacy, expected):
    monkeypatch.setenv("QUINTACLE_VISION", legacy)
    assert image_policy.image_provider() == expected


def test_unset_legacy_defaults_local(clean_policy):
    assert image_policy.image_provider() == "local"


def test_image_provider_env_beats_legacy(monkeypatch, clean_policy):
    monkeypatch.setenv("QUINTACLE_VISION", "auto")
    monkeypatch.setenv("QUINTACLE_IMAGE_PROVIDER", "local")
    assert image_policy.image_provider() == "local"


def test_legacy_warning_logged_once(monkeypatch, clean_policy, caplog):
    monkeypatch.setenv("QUINTACLE_VISION", "cloud")
    with caplog.at_level("WARNING", logger="quintacle_core.perception.image_policy"):
        image_policy.image_provider()
        image_policy.image_provider()
        image_policy.image_provider()
    warnings = [r for r in caplog.records if "deprecated" in r.getMessage()]
    assert len(warnings) == 1
    assert "QUINTACLE_IMAGE_PROVIDER" in warnings[0].getMessage()


def test_no_warning_when_legacy_unset(clean_policy, caplog):
    with caplog.at_level("WARNING", logger="quintacle_core.perception.image_policy"):
        image_policy.image_provider()
    assert not [r for r in caplog.records if "deprecated" in r.getMessage()]


def test_legacy_cloud_describe_images_tries_local_first(monkeypatch, clean_policy):
    monkeypatch.setenv("QUINTACLE_VISION", "cloud")

    def cloud_must_not_run(*a, **k):
        raise AssertionError("legacy cloud must not make describe_images cloud-first")

    monkeypatch.setattr(drop, "_describe_images_cloud", cloud_must_not_run)
    monkeypatch.setattr(local_vlm, "describe_images_local", lambda photos, question=None: "local says")

    assert drop.describe_images(PHOTOS) == "local says"


def test_legacy_cloud_only_a_fallback_when_local_fails(monkeypatch, clean_policy):
    monkeypatch.setenv("QUINTACLE_VISION", "cloud")
    monkeypatch.setattr(drop, "_describe_images_local", lambda photos, question=None: None)
    monkeypatch.setattr(drop, "_describe_images_cloud", lambda photos, question=None: "cloud fallback")

    assert drop.describe_images(PHOTOS) == "cloud fallback"


def test_private_pins_local_even_with_legacy_cloud(monkeypatch, clean_policy):
    monkeypatch.setenv("QUINTACLE_VISION", "cloud")
    monkeypatch.setattr(drop, "_describe_images_local", lambda photos, question=None: None)

    def cloud_must_not_run(*a, **k):
        raise AssertionError("private must never reach the cloud")

    monkeypatch.setattr(drop, "_describe_images_cloud", cloud_must_not_run)
    with pytest.raises(image_policy.LocalImageUnavailable):
        drop.describe_images(PHOTOS, private=True)


def test_describe_images_reads_no_env_itself():
    # Single source of truth: the legacy var is read only in image_policy.
    import inspect

    assert "QUINTACLE_VISION" not in inspect.getsource(drop.describe_images).split('"""', 2)[2]
