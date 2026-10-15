"""QUINTACLE_VISION dispatch + the Ollama-backed local VLM client.

Every test stubs the network edges (Anthropic client / Ollama HTTP) — no
test here spends cloud budget or needs a running Ollama daemon. The one
real local smoke lives outside the suite (run manually, see
docs/navigatr-vlm-notes.md)."""

from __future__ import annotations

import base64

import httpx
import pytest

import quintacle_core.local_vlm as local_vlm
import quintacle_core.local_vlm.ollama as ollama_mod
from quintacle_core.nodes.kb import drop
from quintacle_core.nodes.vision import vision_prompt

PHOTOS = [(b"jpeg-bytes", "image/jpeg")]


# --- the QUINTACLE_VISION dispatch in describe_images ---


def _cloud_must_not_run(*args, **kwargs):
    raise AssertionError("cloud vision must not be called in this mode")


def _local_must_not_run(*args, **kwargs):
    raise AssertionError("local vision must not be called in this mode")


def test_default_is_cloud_and_never_touches_local(monkeypatch):
    monkeypatch.delenv("QUINTACLE_VISION", raising=False)
    monkeypatch.setattr(drop, "_describe_images_cloud", lambda photos, question=None: "cloud says")
    monkeypatch.setattr(local_vlm, "describe_images_local", _local_must_not_run)

    assert drop.describe_images(PHOTOS, "what is it?") == "cloud says"


def test_explicit_cloud_same_as_default(monkeypatch):
    monkeypatch.setenv("QUINTACLE_VISION", "cloud")
    monkeypatch.setattr(drop, "_describe_images_cloud", lambda photos, question=None: "cloud says")
    monkeypatch.setattr(local_vlm, "describe_images_local", _local_must_not_run)

    assert drop.describe_images(PHOTOS) == "cloud says"


def test_local_mode_uses_local_backend(monkeypatch):
    monkeypatch.setenv("QUINTACLE_VISION", "local")
    calls = {}

    def fake_local(photos, question=None):
        calls["photos"], calls["question"] = photos, question
        return "local says"

    monkeypatch.setattr(local_vlm, "describe_images_local", fake_local)
    monkeypatch.setattr(drop, "_describe_images_cloud", _cloud_must_not_run)

    assert drop.describe_images(PHOTOS, "how many boats?") == "local says"
    assert calls == {"photos": PHOTOS, "question": "how many boats?"}


def test_local_mode_unavailable_raises_instead_of_billing_cloud(monkeypatch):
    monkeypatch.setenv("QUINTACLE_VISION", "local")
    monkeypatch.setattr(local_vlm, "describe_images_local", lambda photos, question=None: None)
    monkeypatch.setattr(drop, "_describe_images_cloud", _cloud_must_not_run)

    with pytest.raises(RuntimeError, match="local vision is unavailable"):
        drop.describe_images(PHOTOS)


def test_auto_prefers_local(monkeypatch):
    monkeypatch.setenv("QUINTACLE_VISION", "auto")
    monkeypatch.setattr(local_vlm, "describe_images_local", lambda photos, question=None: "local says")
    monkeypatch.setattr(drop, "_describe_images_cloud", _cloud_must_not_run)

    assert drop.describe_images(PHOTOS) == "local says"


def test_auto_falls_back_to_cloud_with_log_line(monkeypatch, caplog):
    monkeypatch.setenv("QUINTACLE_VISION", "auto")
    monkeypatch.setattr(local_vlm, "describe_images_local", lambda photos, question=None: None)
    monkeypatch.setattr(drop, "_describe_images_cloud", lambda photos, question=None: "cloud fallback")

    with caplog.at_level("WARNING", logger="quintacle_core.nodes.kb.drop"):
        assert drop.describe_images(PHOTOS) == "cloud fallback"
    assert any("falling back to cloud" in r.message for r in caplog.records)


# --- the Ollama HTTP client itself (describe_images_local) ---


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


def test_local_call_shape_and_success(monkeypatch):
    monkeypatch.delenv("QUINTACLE_OLLAMA_URL", raising=False)
    monkeypatch.delenv("QUINTACLE_VISION_MODEL", raising=False)
    seen = {}

    def fake_post(url, json=None, timeout=None):
        seen["url"], seen["json"], seen["timeout"] = url, json, timeout
        return FakeResponse(payload={"message": {"role": "assistant", "content": "  a desk with a red mug  "}})

    monkeypatch.setattr(httpx, "post", fake_post)

    out = ollama_mod.describe_images_local(PHOTOS, "what's on the desk?")

    assert out == "a desk with a red mug"
    assert seen["url"] == "http://localhost:11434/api/chat"
    assert seen["json"]["model"] == "qwen2.5vl:3b"
    assert seen["json"]["stream"] is False
    (message,) = seen["json"]["messages"]
    assert message["role"] == "user"
    assert message["content"] == vision_prompt(1, "what's on the desk?")
    assert message["images"] == [base64.standard_b64encode(b"jpeg-bytes").decode()]


def test_local_env_overrides_url_and_model(monkeypatch):
    monkeypatch.setenv("QUINTACLE_OLLAMA_URL", "http://10.0.0.5:11434/")
    monkeypatch.setenv("QUINTACLE_VISION_MODEL", "moondream")
    seen = {}

    def fake_post(url, json=None, timeout=None):
        seen["url"], seen["model"] = url, json["model"]
        return FakeResponse(payload={"message": {"content": "ok"}})

    monkeypatch.setattr(httpx, "post", fake_post)

    assert ollama_mod.describe_images_local(PHOTOS) == "ok"
    assert seen["url"] == "http://10.0.0.5:11434/api/chat"
    assert seen["model"] == "moondream"


def test_daemon_down_returns_none(monkeypatch):
    def fake_post(url, json=None, timeout=None):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "post", fake_post)
    assert ollama_mod.describe_images_local(PHOTOS) is None


def test_model_not_pulled_returns_none(monkeypatch):
    monkeypatch.setattr(
        httpx, "post", lambda url, json=None, timeout=None: FakeResponse(status_code=404, payload={"error": 'model "qwen2.5vl:3b" not found'})
    )
    assert ollama_mod.describe_images_local(PHOTOS) is None


def test_empty_answer_returns_none(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda url, json=None, timeout=None: FakeResponse(payload={"message": {"content": "   "}}))
    assert ollama_mod.describe_images_local(PHOTOS) is None


def test_unparseable_response_returns_none(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda url, json=None, timeout=None: FakeResponse(payload=None, text="<html>proxy error</html>"))
    assert ollama_mod.describe_images_local(PHOTOS) is None
