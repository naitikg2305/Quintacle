"""Provider-aware structured-parse dispatch (llm_dispatch.parse_structured):
local via stubbed Ollama HTTP, cloud via a stubbed Anthropic parse, the auto
fallback, env/arg precedence, the readable hard failures, and the endpoint
plumbing (?provider=... in, provider_used out). No live API calls and no
running daemon needed — every network edge is stubbed, same style as
test_local_vlm / test_chat_models."""

from __future__ import annotations

import io
import json
import urllib.error

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

import quintacle_core.api as api_module
import quintacle_core.llm_dispatch as llm_dispatch
from quintacle_core.llm_dispatch import (
    DEFAULT_LOCAL_PARSE_MODEL,
    LocalParseError,
    OllamaError,
    collect_providers,
    parse_structured,
    summarize_providers,
)


class Fruit(BaseModel):
    name: str
    count: int


class _FakeResponse(io.BytesIO):
    """Just enough of urlopen's return for `with ... as resp: json.load(resp)`."""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _stub_ollama(monkeypatch, content: str, calls: list | None = None):
    """Stubs the Ollama HTTP edge: captures each request payload, answers
    with `content` as the message body."""

    def fake_urlopen(req, timeout=None):
        if calls is not None:
            calls.append(json.loads(req.data.decode()))
        return _FakeResponse(json.dumps({"message": {"role": "assistant", "content": content}}).encode())

    monkeypatch.setattr(llm_dispatch.urllib.request, "urlopen", fake_urlopen)


def _stub_ollama_down(monkeypatch):
    def fake_urlopen(req, timeout=None):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(llm_dispatch.urllib.request, "urlopen", fake_urlopen)


def _cloud_must_not_run(*args, **kwargs):
    raise AssertionError("cloud parse must not be called in this mode")


def _local_must_not_run(*args, **kwargs):
    raise AssertionError("local parse must not be called in this mode")


# --- local happy path ---


def test_local_parses_schema_valid_json(monkeypatch):
    calls: list[dict] = []
    _stub_ollama(monkeypatch, '{"name": "apple", "count": 3}', calls)
    monkeypatch.setattr(llm_dispatch, "_parse_cloud", _cloud_must_not_run)

    result = parse_structured("count fruit", "three apples", Fruit, provider="local")

    assert result.provider_used == "local"
    assert result.parsed == Fruit(name="apple", count=3)
    # The request really used Ollama's schema-constrained generation on the
    # default parse model, with the system/user split intact.
    payload = calls[0]
    assert payload["model"] == DEFAULT_LOCAL_PARSE_MODEL
    assert payload["format"] == Fruit.model_json_schema()
    assert payload["messages"][0] == {"role": "system", "content": "count fruit"}
    assert payload["messages"][1] == {"role": "user", "content": "three apples"}


def test_local_parse_model_env_overrides_default(monkeypatch):
    calls: list[dict] = []
    _stub_ollama(monkeypatch, '{"name": "apple", "count": 3}', calls)
    monkeypatch.setenv("QUINTACLE_LOCAL_PARSE_MODEL", "qwen3:14b")

    parse_structured("count fruit", "three apples", Fruit, provider="local")

    assert calls[0]["model"] == "qwen3:14b"


# --- auto: local first, cloud fallback ---


def test_auto_prefers_local_when_it_works(monkeypatch):
    monkeypatch.delenv("QUINTACLE_INGEST_PROVIDER", raising=False)
    _stub_ollama(monkeypatch, '{"name": "pear", "count": 1}')
    monkeypatch.setattr(llm_dispatch, "_parse_cloud", _cloud_must_not_run)

    result = parse_structured("count fruit", "a pear", Fruit)  # no provider, no env -> auto

    assert result.provider_used == "local"
    assert result.parsed.name == "pear"


def test_auto_falls_back_to_cloud_on_schema_invalid_local_output(monkeypatch, caplog):
    monkeypatch.delenv("QUINTACLE_INGEST_PROVIDER", raising=False)
    _stub_ollama(monkeypatch, '{"name": "pear"}')  # missing required `count`
    monkeypatch.setattr(llm_dispatch, "_parse_cloud", lambda *a, **k: Fruit(name="cloud pear", count=2))

    with caplog.at_level("WARNING"):
        result = parse_structured("count fruit", "a pear", Fruit)

    assert result.provider_used == "cloud"
    assert result.parsed == Fruit(name="cloud pear", count=2)
    assert any("falling back to cloud" in r.message for r in caplog.records)


def test_auto_falls_back_to_cloud_when_daemon_is_down(monkeypatch):
    _stub_ollama_down(monkeypatch)
    monkeypatch.setattr(llm_dispatch, "_parse_cloud", lambda *a, **k: Fruit(name="cloud", count=0))

    result = parse_structured("count fruit", "anything", Fruit, provider="auto")

    assert result.provider_used == "cloud"


# --- hard failures stay readable ---


def test_provider_local_daemon_down_raises_readable_ollama_error(monkeypatch):
    _stub_ollama_down(monkeypatch)
    monkeypatch.setattr(llm_dispatch, "_parse_cloud", _cloud_must_not_run)

    with pytest.raises(OllamaError, match="isn't reachable"):
        parse_structured("count fruit", "anything", Fruit, provider="local")


def test_provider_local_schema_invalid_raises_readable_local_parse_error(monkeypatch):
    _stub_ollama(monkeypatch, "not json at all")
    monkeypatch.setattr(llm_dispatch, "_parse_cloud", _cloud_must_not_run)

    with pytest.raises(LocalParseError, match="doesn't match the Fruit schema"):
        parse_structured("count fruit", "anything", Fruit, provider="local")


def test_unknown_provider_raises_value_error(monkeypatch):
    with pytest.raises(ValueError, match="unknown ingest provider"):
        parse_structured("s", "u", Fruit, provider="turbo")


# --- cloud path + env/arg precedence ---


def test_provider_cloud_never_touches_local(monkeypatch):
    monkeypatch.setattr(llm_dispatch, "_parse_local", _local_must_not_run)
    monkeypatch.setattr(llm_dispatch, "_parse_cloud", lambda *a, **k: Fruit(name="cloud", count=9))

    result = parse_structured("count fruit", "anything", Fruit, provider="cloud")

    assert result.provider_used == "cloud"
    assert result.parsed.count == 9


def test_env_default_is_used_when_no_provider_arg(monkeypatch):
    monkeypatch.setenv("QUINTACLE_INGEST_PROVIDER", "cloud")
    monkeypatch.setattr(llm_dispatch, "_parse_local", _local_must_not_run)
    monkeypatch.setattr(llm_dispatch, "_parse_cloud", lambda *a, **k: Fruit(name="cloud", count=1))

    assert parse_structured("s", "u", Fruit).provider_used == "cloud"


def test_provider_arg_wins_over_env(monkeypatch):
    monkeypatch.setenv("QUINTACLE_INGEST_PROVIDER", "cloud")
    _stub_ollama(monkeypatch, '{"name": "local wins", "count": 1}')
    monkeypatch.setattr(llm_dispatch, "_parse_cloud", _cloud_must_not_run)

    assert parse_structured("s", "u", Fruit, provider="local").provider_used == "local"


# --- the per-request provider collector ---


def test_collector_summarizes_local_cloud_and_mixed(monkeypatch):
    monkeypatch.setattr(llm_dispatch, "_parse_cloud", lambda *a, **k: Fruit(name="c", count=1))
    _stub_ollama(monkeypatch, '{"name": "l", "count": 1}')

    used = collect_providers()
    assert summarize_providers(used) is None  # nothing routed yet

    parse_structured("s", "u", Fruit, provider="local")
    assert summarize_providers(used) == "local"

    parse_structured("s", "u", Fruit, provider="cloud")
    assert summarize_providers(used) == "mixed"


# --- one routed site end-to-end (journal parse) ---


def test_parse_journal_dump_routes_through_local(monkeypatch):
    from quintacle_core.nodes.journal.llm import parse_journal_dump

    parsed = {
        "entries": [
            {"type": "activity", "category": "productivity", "description": "coding", "hours": 2.0}
        ]
    }
    _stub_ollama(monkeypatch, json.dumps(parsed))
    monkeypatch.setattr(llm_dispatch, "_parse_cloud", _cloud_must_not_run)

    # Text chosen to dodge the date-signal regex (no second resolver call) and
    # produce no finance entries (no kind resolver call) — exactly one parse.
    entries = parse_journal_dump("did some coding for two hours", provider="local")

    assert len(entries) == 1
    assert entries[0].type == "activity"
    assert entries[0].hours == 2.0


# --- endpoint plumbing: ?provider= in, provider_used out ---


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "DATA_DIR", tmp_path)
    return TestClient(api_module.create_app())


def test_journal_parse_endpoint_plumbs_provider_and_reports_it(client, monkeypatch):
    parsed = {
        "entries": [
            {"type": "activity", "category": "productivity", "description": "coding", "hours": 2.0}
        ]
    }
    _stub_ollama(monkeypatch, json.dumps(parsed))
    monkeypatch.setattr(llm_dispatch, "_parse_cloud", _cloud_must_not_run)

    resp = client.post(
        "/journal/2026-10-15/parse?provider=local",
        content="did some coding for two hours",
        headers={"content-type": "text/plain"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["provider_used"] == "local"
    assert body["entries"][0]["description"] == "coding"


def test_journal_parse_endpoint_local_failure_is_a_readable_400(client, monkeypatch):
    _stub_ollama_down(monkeypatch)
    monkeypatch.setattr(llm_dispatch, "_parse_cloud", _cloud_must_not_run)

    resp = client.post(
        "/journal/2026-10-15/parse?provider=local",
        content="did some coding for two hours",
        headers={"content-type": "text/plain"},
    )

    assert resp.status_code == 400
    assert "Ollama" in resp.json()["detail"]


def test_kb_sort_endpoint_plumbs_provider_cloud(client, monkeypatch):
    from quintacle_core.nodes.kb.llm import KBSuggestion

    monkeypatch.setattr(llm_dispatch, "_parse_local", _local_must_not_run)
    monkeypatch.setattr(
        llm_dispatch, "_parse_cloud", lambda *a, **k: KBSuggestion(folder="Nerd Folder/Projects", title="T", content="C")
    )

    resp = client.post("/kb/sort?provider=cloud", content="an idea", headers={"content-type": "text/plain"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["provider_used"] == "cloud"
    assert body["folder"] == "Nerd Folder/Projects"


def test_drop_endpoint_plumbs_provider_and_reports_top_level(client, monkeypatch):
    # "note:" prefix -> deterministic kb_entry route -> one suggest_kb_entry
    # parse; text dodges the experience/person additive regex gates.
    suggestion = '{"folder": "Nerd Folder/Projects", "title": "Monitor arm", "content": "height 47cm", "links": []}'
    _stub_ollama(monkeypatch, suggestion)
    monkeypatch.setattr(llm_dispatch, "_parse_cloud", _cloud_must_not_run)

    resp = client.post("/drop", data={"text": "note: monitor arm height is 47cm", "provider": "local"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["provider_used"] == "local"
    assert body["entries"][0]["type"] == "kb_entry"
    assert body["entries"][0]["title"] == "Monitor arm"


def test_drop_endpoint_rejects_bogus_provider(client):
    resp = client.post("/drop", data={"text": "note: hi", "provider": "turbo"})
    assert resp.status_code == 400
