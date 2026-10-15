"""QUINTACLE_VISION_BACKEND selection + the llama-server-backed VLM client.

Same rules as test_local_vlm.py: every test stubs the HTTP edge — nothing
here needs a running llama-server or Ollama daemon. The one real smoke
(llama-server + Qwen2.5-VL GGUF) lives outside the suite; see
phone/tier3-vlm/README.md."""

from __future__ import annotations

import base64

import httpx

import quintacle_core.local_vlm as local_vlm
import quintacle_core.local_vlm.llamacpp as llamacpp_mod
import quintacle_core.local_vlm.ollama as ollama_mod
from quintacle_core.nodes.vision import vision_prompt

PHOTOS = [(b"jpeg-bytes", "image/jpeg")]


# --- the QUINTACLE_VISION_BACKEND selection in local_vlm.describe_images_local ---


def _must_not_run(*args, **kwargs):
    raise AssertionError("this backend must not be called in this mode")


def test_default_backend_is_ollama(monkeypatch):
    monkeypatch.delenv("QUINTACLE_VISION_BACKEND", raising=False)
    monkeypatch.setattr(ollama_mod, "describe_images_local", lambda photos, question=None: "ollama says")
    monkeypatch.setattr(llamacpp_mod, "describe_images_llamacpp", _must_not_run)

    assert local_vlm.describe_images_local(PHOTOS, "what is it?") == "ollama says"


def test_explicit_ollama_same_as_default(monkeypatch):
    monkeypatch.setenv("QUINTACLE_VISION_BACKEND", "ollama")
    monkeypatch.setattr(ollama_mod, "describe_images_local", lambda photos, question=None: "ollama says")
    monkeypatch.setattr(llamacpp_mod, "describe_images_llamacpp", _must_not_run)

    assert local_vlm.describe_images_local(PHOTOS) == "ollama says"


def test_llamacpp_backend_routes_with_args_intact(monkeypatch):
    monkeypatch.setenv("QUINTACLE_VISION_BACKEND", "llamacpp")
    calls = {}

    def fake_llamacpp(photos, question=None):
        calls["photos"], calls["question"] = photos, question
        return "llamacpp says"

    monkeypatch.setattr(llamacpp_mod, "describe_images_llamacpp", fake_llamacpp)
    monkeypatch.setattr(ollama_mod, "describe_images_local", _must_not_run)

    assert local_vlm.describe_images_local(PHOTOS, "how many boats?") == "llamacpp says"
    assert calls == {"photos": PHOTOS, "question": "how many boats?"}


def test_backend_env_is_trimmed_and_lowercased(monkeypatch):
    monkeypatch.setenv("QUINTACLE_VISION_BACKEND", "  LlamaCPP ")
    monkeypatch.setattr(llamacpp_mod, "describe_images_llamacpp", lambda photos, question=None: "llamacpp says")
    monkeypatch.setattr(ollama_mod, "describe_images_local", _must_not_run)

    assert local_vlm.describe_images_local(PHOTOS) == "llamacpp says"


def test_llamacpp_backend_none_passes_through(monkeypatch):
    # None (server down) must reach the QUINTACLE_VISION dispatch untouched —
    # that's what "auto falls back to cloud" hangs off.
    monkeypatch.setenv("QUINTACLE_VISION_BACKEND", "llamacpp")
    monkeypatch.setattr(llamacpp_mod, "describe_images_llamacpp", lambda photos, question=None: None)
    monkeypatch.setattr(ollama_mod, "describe_images_local", _must_not_run)

    assert local_vlm.describe_images_local(PHOTOS) is None


# --- the llama-server HTTP client itself (describe_images_llamacpp) ---


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


def _ok(content="ok"):
    return FakeResponse(payload={"choices": [{"message": {"role": "assistant", "content": content}}]})


def test_llamacpp_call_shape_and_success(monkeypatch):
    monkeypatch.delenv("QUINTACLE_LLAMACPP_URL", raising=False)
    monkeypatch.delenv("QUINTACLE_VISION_MODEL", raising=False)
    seen = {}

    def fake_post(url, json=None, timeout=None):
        seen["url"], seen["json"], seen["timeout"] = url, json, timeout
        return _ok("  a desk with a red mug  ")

    monkeypatch.setattr(httpx, "post", fake_post)

    out = llamacpp_mod.describe_images_llamacpp(PHOTOS, "what's on the desk?")

    assert out == "a desk with a red mug"
    assert seen["url"] == "http://127.0.0.1:8080/v1/chat/completions"
    assert seen["json"]["stream"] is False
    # llama-server hosts exactly one model; no model field unless pinned by env.
    assert "model" not in seen["json"]
    (message,) = seen["json"]["messages"]
    assert message["role"] == "user"
    image_part, text_part = message["content"]
    b64 = base64.standard_b64encode(b"jpeg-bytes").decode()
    assert image_part == {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
    assert text_part == {"type": "text", "text": vision_prompt(1, "what's on the desk?")}


def test_llamacpp_multiple_photos_keep_order_and_mime(monkeypatch):
    photos = [(b"one", "image/png"), (b"two", "image/webp")]

    def fake_post(url, json=None, timeout=None):
        (message,) = json["messages"]
        parts = message["content"]
        assert [p["type"] for p in parts] == ["image_url", "image_url", "text"]
        assert parts[0]["image_url"]["url"].startswith("data:image/png;base64,")
        assert parts[1]["image_url"]["url"].startswith("data:image/webp;base64,")
        assert parts[2]["text"] == vision_prompt(2, None)
        return _ok()

    monkeypatch.setattr(httpx, "post", fake_post)
    assert llamacpp_mod.describe_images_llamacpp(photos) == "ok"


def test_llamacpp_env_overrides_url_and_pins_model(monkeypatch):
    monkeypatch.setenv("QUINTACLE_LLAMACPP_URL", "http://10.0.0.5:8081/")
    monkeypatch.setenv("QUINTACLE_VISION_MODEL", "qwen2.5-vl-3b")
    seen = {}

    def fake_post(url, json=None, timeout=None):
        seen["url"], seen["model"] = url, json.get("model")
        return _ok()

    monkeypatch.setattr(httpx, "post", fake_post)

    assert llamacpp_mod.describe_images_llamacpp(PHOTOS) == "ok"
    assert seen["url"] == "http://10.0.0.5:8081/v1/chat/completions"
    assert seen["model"] == "qwen2.5-vl-3b"


def test_llamacpp_server_down_returns_none(monkeypatch):
    def fake_post(url, json=None, timeout=None):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "post", fake_post)
    assert llamacpp_mod.describe_images_llamacpp(PHOTOS) is None


def test_llamacpp_error_status_returns_none(monkeypatch):
    # llama-server without --mmproj rejects image parts with a 500.
    monkeypatch.setattr(
        httpx,
        "post",
        lambda url, json=None, timeout=None: FakeResponse(
            status_code=500, payload={"error": {"message": "image input is not supported - hint: if this is unexpected, you may need to provide the mmproj"}}
        ),
    )
    assert llamacpp_mod.describe_images_llamacpp(PHOTOS) is None


def test_llamacpp_error_status_unparseable_body_returns_none(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda url, json=None, timeout=None: FakeResponse(status_code=502, payload=None, text="<html>bad gateway</html>"))
    assert llamacpp_mod.describe_images_llamacpp(PHOTOS) is None


def test_llamacpp_empty_answer_returns_none(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda url, json=None, timeout=None: _ok("   "))
    assert llamacpp_mod.describe_images_llamacpp(PHOTOS) is None


def test_llamacpp_no_choices_returns_none(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda url, json=None, timeout=None: FakeResponse(payload={"choices": []}))
    assert llamacpp_mod.describe_images_llamacpp(PHOTOS) is None


def test_llamacpp_unparseable_response_returns_none(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda url, json=None, timeout=None: FakeResponse(payload=None, text="<html>proxy error</html>"))
    assert llamacpp_mod.describe_images_llamacpp(PHOTOS) is None
