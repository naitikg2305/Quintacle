"""Claude Max backend (max_backend.py) — always against a FAKE `claude`
binary; the real CLI would spend subscription usage."""
from __future__ import annotations

import json
import stat
import sys
from types import SimpleNamespace

import anthropic
import pytest
from pydantic import BaseModel

from quintacle_core import max_backend
from quintacle_core.nodes.kb import chat


class Kind(BaseModel):
    kind: str
    item: str


def _fake_cli(tmp_path, *, result: dict | None = None, exit_code: int = 0):
    """A python script standing in for `claude`: records argv, env and the
    stdin message, then prints one stream-json result event."""
    log = tmp_path / "calls.jsonl"
    out = result if result is not None else {
        "type": "result", "subtype": "success", "is_error": False,
        "result": '{"kind":"food","item":"burrito bowl"}',
        "structured_output": {"kind": "food", "item": "burrito bowl"},
        "modelUsage": {"claude-haiku-5-5": {}},
    }
    script = tmp_path / "claude"
    script.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        f"open({str(log)!r}, 'a').write(json.dumps({{'argv': sys.argv[1:], "
        "'has_key': 'ANTHROPIC_API_KEY' in os.environ, 'stdin': sys.stdin.read()}) + '\\n')\n"
        "print(json.dumps({'type': 'system'}))\n"
        f"print(json.dumps({out!r}))\n"
        f"sys.exit({exit_code})\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script, log


@pytest.fixture
def max_on(monkeypatch):
    monkeypatch.delenv("QUINTACLE_DISABLE_MAX", raising=False)
    monkeypatch.delenv("QUINTACLE_CLOUD", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")


def _calls(log):
    return [json.loads(line) for line in log.read_text().splitlines()]


def test_parse_goes_through_max_with_key_stripped(tmp_path, monkeypatch, max_on):
    script, log = _fake_cli(tmp_path)
    monkeypatch.setenv("QUINTACLE_CLAUDE_BIN", str(script))
    monkeypatch.setattr(anthropic, "Anthropic", lambda: pytest.fail("API must not be called when Max answers"))
    resp = max_backend.cloud_client().messages.parse(
        model="claude-haiku-4-5", max_tokens=100, system="classify", messages=[{"role": "user", "content": "burrito"}],
        output_format=Kind,
    )
    assert resp.parsed_output == Kind(kind="food", item="burrito bowl")
    (call,) = _calls(log)
    assert call["has_key"] is False  # would otherwise bill the API, not the subscription
    argv = call["argv"]
    assert argv[argv.index("--model") + 1] == "haiku"
    assert "--json-schema" in argv and argv[argv.index("--tools") + 1] == ""
    assert argv[argv.index("--setting-sources") + 1] == ""  # no hooks fire


def test_image_blocks_pass_through(tmp_path, monkeypatch, max_on):
    script, log = _fake_cli(tmp_path)
    monkeypatch.setenv("QUINTACLE_CLAUDE_BIN", str(script))
    img = {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AAAA"}}
    max_backend.cloud_client().messages.parse(
        model="claude-haiku-4-5", system="x", messages=[{"role": "user", "content": [img, {"type": "text", "text": "what"}]}],
        output_format=Kind,
    )
    sent = json.loads(_calls(log)[0]["stdin"])
    assert sent["message"]["content"][0] == img


def test_max_failure_falls_back_to_api(tmp_path, monkeypatch, max_on):
    script, _ = _fake_cli(tmp_path, result={"type": "result", "subtype": "error", "is_error": True, "result": "usage limit reached"})
    monkeypatch.setenv("QUINTACLE_CLAUDE_BIN", str(script))
    seen = {}

    class FakeAPI:
        class messages:
            @staticmethod
            def parse(**kw):
                seen.update(kw)
                return SimpleNamespace(parsed_output=Kind(kind="note", item="api"))

    monkeypatch.setattr(anthropic, "Anthropic", lambda: FakeAPI())
    resp = max_backend.cloud_client().messages.parse(
        model="claude-haiku-4-5", max_tokens=50, system="s", messages=[{"role": "user", "content": "x"}], output_format=Kind,
    )
    assert resp.parsed_output.item == "api" and seen["model"] == "claude-haiku-4-5"


def test_missing_cli_goes_straight_to_api(tmp_path, monkeypatch, max_on):
    """The phone case: no `claude` on PATH."""
    monkeypatch.setenv("QUINTACLE_CLAUDE_BIN", str(tmp_path / "nope"))
    assert max_backend.available() is False

    class FakeAPI:
        class messages:
            @staticmethod
            def create(**kw):
                return SimpleNamespace(content=[SimpleNamespace(type="text", text="from api")])

    monkeypatch.setattr(anthropic, "Anthropic", lambda: FakeAPI())
    resp = max_backend.cloud_client().messages.create(model="claude-haiku-4-5", max_tokens=10, messages=[{"role": "user", "content": "hi"}])
    assert resp.content[0].text == "from api"


def test_cloud_api_mode_and_test_default_skip_max(monkeypatch, max_on):
    monkeypatch.setenv("QUINTACLE_CLOUD", "api")
    assert max_backend.enabled() is False
    monkeypatch.delenv("QUINTACLE_CLOUD")
    monkeypatch.setenv("QUINTACLE_DISABLE_MAX", "1")
    assert max_backend.enabled() is False


def test_multi_turn_flattened_keeps_last_turn_images():
    img = {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AAAA"}}
    out = max_backend._flatten_messages([
        {"role": "user", "content": "first q"},
        {"role": "assistant", "content": "first a"},
        {"role": "user", "content": [img, {"type": "text", "text": "and this?"}]},
    ])
    assert out[0] == img
    assert "User: first q" in out[1]["text"] and "Assistant: first a" in out[1]["text"] and out[1]["text"].endswith("and this?")


def test_chat_max_model_resolves_and_falls_back_with_note(tmp_path, monkeypatch, max_on):
    assert chat.resolve_model("max:opus", False)["provider"] == "max"
    monkeypatch.setenv("QUINTACLE_CLAUDE_BIN", str(tmp_path / "nope"))
    monkeypatch.setattr(chat, "_run_anthropic", lambda m, msgs, kb: f"api reply via {m}")
    reply = chat._run_max("max:opus", [{"role": "user", "content": "hi"}], "kb")
    assert reply.startswith("api reply via claude-opus-5-5") and "Claude Max wasn't available" in reply


def test_chat_max_uses_web_tools(tmp_path, monkeypatch, max_on):
    script, log = _fake_cli(tmp_path, result={"type": "result", "subtype": "success", "is_error": False, "result": "hello"})
    monkeypatch.setenv("QUINTACLE_CLAUDE_BIN", str(script))
    assert chat._run_max("max:sonnet", [{"role": "user", "content": "hi"}], "KB TEXT") == "hello"
    argv = _calls(log)[0]["argv"]
    assert argv[argv.index("--tools") + 1] == "WebSearch,WebFetch"
    assert argv[argv.index("--model") + 1] == "sonnet"
    assert "KB TEXT" in argv[argv.index("--system-prompt") + 1]


def test_clean_schema_drops_discriminator():
    schema = {"oneOf": [{"type": "object"}], "discriminator": {"propertyName": "type"}, "$defs": {"A": {"discriminator": 1, "type": "object"}}}
    assert max_backend.clean_schema(schema) == {"oneOf": [{"type": "object"}], "$defs": {"A": {"type": "object"}}}
