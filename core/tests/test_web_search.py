"""Web lane for models without native search (web_search.py, 2026-11-05).
NO real network: urllib.request.urlopen is stubbed everywhere."""
from __future__ import annotations

import io
import urllib.parse

import pytest
from fastapi.testclient import TestClient

import quintacle_core.api as api_module
import quintacle_core.retrieval as retrieval
from quintacle_core import web_search
from quintacle_core.nodes.kb import chat

DDG_FIXTURE = """
<html><body>
<div class="result results_links results_links_deep web-result">
  <h2 class="result__title"><a rel="nofollow" class="result__a"
     href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fvisa&amp;rut=abc">Japan Visa &amp; Entry Requirements</a></h2>
  <a class="result__snippet" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fvisa">US citizens can stay <b>90 days</b> visa-free.</a>
</div>
<div class="result results_links web-result">
  <h2 class="result__title"><a rel="nofollow" class="result__a" href="https://travel.example.org/japan">Japan travel guide</a></h2>
  <a class="result__snippet" href="https://travel.example.org/japan">Everything about entry.</a>
</div>
<div class="result result--ad"><a class="result__a" href="https://duckduckgo.com/y.js?ad=1">Ad</a></div>
</body></html>
"""

PAGE = """<html><head><title>t</title><script>var secret = 1;</script><style>p{}</style></head>
<body><nav>Home | About</nav><header>Site header</header>
<article><h1>Entry rules</h1><p>Visitors may stay 90 days.</p><p>Passport must be valid.</p></article>
<footer>Copyright</footer></body></html>"""

NOTE_TEXT = "Kyoto itinerary private detail zanzibarquokka"


class _Resp(io.BytesIO):
    def __init__(self, body: str, ctype: str = "text/html; charset=utf-8"):
        super().__init__(body.encode())
        self.headers = {"Content-Type": ctype}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def net(monkeypatch):
    """Stubbed urlopen: DDG → fixture, other URLs → PAGE. Records every URL."""
    monkeypatch.delenv("QUINTACLE_WEB_SEARCH", raising=False)
    monkeypatch.delenv("QUINTACLE_SEARXNG_URL", raising=False)
    monkeypatch.delenv("QUINTACLE_BRAVE_API_KEY", raising=False)
    # These stubs serve DDG-shaped HTML; DDG is opt-in since 2026-11-05.
    monkeypatch.setenv("QUINTACLE_WEB_BACKEND", "ddg")
    seen: list[str] = []

    def fake(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else req
        seen.append(url)
        if url.startswith(web_search.DDG_URL):
            return _Resp(DDG_FIXTURE)
        return _Resp(PAGE)

    monkeypatch.setattr(web_search.urllib.request, "urlopen", fake)
    return seen


def test_parse_ddg_html_unwraps_and_skips_ads():
    res = web_search.parse_ddg_html(DDG_FIXTURE)
    assert [r["url"] for r in res] == ["https://example.com/visa", "https://travel.example.org/japan"]
    assert res[0]["title"] == "Japan Visa & Entry Requirements"
    assert res[0]["snippet"] == "US citizens can stay 90 days visa-free."


def test_html_to_text_strips_scripts_and_nav():
    text = web_search.html_to_text(PAGE)
    assert "Visitors may stay 90 days." in text and "Passport must be valid." in text
    for junk in ("secret", "Home | About", "Site header", "Copyright", "p{}"):
        assert junk not in text


def test_fetch_text_caps_and_degrades(net, monkeypatch):
    assert "Visitors may stay" in web_search.fetch_text("https://x.example/a")
    assert len(web_search.fetch_text("https://x.example/a", max_chars=20)) <= 22
    assert web_search.fetch_text("file:///etc/passwd") == ""

    def boom(req, timeout=None):
        raise OSError("down")

    monkeypatch.setattr(web_search.urllib.request, "urlopen", boom)
    assert web_search.fetch_text("https://x.example/a") == ""
    assert web_search.search("anything") == []


def test_searxng_backend(monkeypatch):
    monkeypatch.setenv("QUINTACLE_SEARXNG_URL", "http://searx.local:8888/")
    seen = []

    def fake(req, timeout=None):
        seen.append(req.full_url)
        return _Resp('{"results":[{"title":"A","url":"https://a.example","content":"aa"},{"title":"bad","url":"javascript:x"}]}', "application/json")

    monkeypatch.setattr(web_search.urllib.request, "urlopen", fake)
    assert web_search.search("q one") == [{"title": "A", "url": "https://a.example", "snippet": "aa"}]
    assert seen[0].startswith("http://searx.local:8888/search?") and "format=json" in seen[0]


@pytest.mark.parametrize(
    "text",
    [
        "what's the latest news on the Artemis mission",
        "price of bitcoin",
        "opening hours of the Smithsonian",
        "how do I renew a passport",
        "Japan visa requirements for US citizens",
        "weather in Baltimore",
        "ramen near me",
        "summarize https://example.com/article",
        "what's the weather for my trip",  # strong external cue beats "my"
    ],
)
def test_needs_web_positives(text):
    assert web_search.needs_web(text)


@pytest.mark.parametrize(
    "text",
    [
        "what did I write in my notes about deadlifts",
        "summarize my trip to Kyoto",
        "what's the latest on my project",
        "who is Laura",
        "how many times did I go to the gym",
        "",
    ],
)
def test_needs_web_negatives(text):
    assert not web_search.needs_web(text)


def test_build_query_strips_filler():
    assert web_search.build_query("Hey, can you please look up the opening hours of the Louvre? thanks") == "the opening hours of the Louvre"


def test_web_block_numbers_sources(net):
    block = web_search.web_block("Japan visa requirements")
    assert block.startswith("## Web results (fetched just now)")
    assert "[1] Japan Visa & Entry Requirements — https://example.com/visa" in block
    assert "[2] Japan travel guide" in block
    assert "Visitors may stay 90 days." in block
    assert "[1], [2]" in block and "don't answer" in block


def test_chat_web_block_provider_and_toggle(net):
    q = "Japan visa requirements"
    assert web_search.chat_web_block("local", None, q)
    assert web_search.chat_web_block("bedrock", None, q)
    for native in ("anthropic", "openai", "max"):
        assert web_search.chat_web_block(native, True, q) is None
    assert web_search.chat_web_block("local", False, q) is None  # toggle off beats auto
    assert web_search.chat_web_block("local", None, "summarize my notes") is None
    assert web_search.chat_web_block("local", True, "summarize Kyoto temples")  # toggle on beats auto
    assert web_search.chat_web_block("local", None, q, mode="serious") is None  # no auto in serious


def test_failures_degrade_to_no_block(monkeypatch):
    monkeypatch.delenv("QUINTACLE_WEB_SEARCH", raising=False)
    monkeypatch.setenv("QUINTACLE_WEB_BACKEND", "ddg")

    def boom(req, timeout=None):
        raise TimeoutError("slow")

    monkeypatch.setattr(web_search.urllib.request, "urlopen", boom)
    assert web_search.chat_web_block("local", True, "Japan visa requirements") is None


# --- through the real /kb/chat endpoint -------------------------------------


@pytest.fixture(autouse=True)
def _reset_retrieval_singleton():
    retrieval._index = None
    yield
    retrieval._index = None


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "DATA_DIR", tmp_path)
    c = TestClient(api_module.create_app())
    assert c.post("/kb/entries", json={"folder": "Travel", "title": "Japan Trip", "content": f"Japan visa requirements: {NOTE_TEXT}"}).status_code == 200
    return c


def _spy(monkeypatch):
    calls = []
    for name in ("_run_anthropic", "_run_openai", "_run_bedrock", "_run_local", "_run_max"):
        def runner(model, messages, kb_text, _n=name):
            calls.append({"runner": _n, "kb_text": kb_text or ""})
            return "ok"

        monkeypatch.setattr(chat, name, runner)
    return calls


@pytest.mark.parametrize("model", ["local:qwen3:8b", "bedrock:us.amazon.nova-lite-v1:0"])
def test_no_native_search_providers_get_web_block(client, net, monkeypatch, model):
    calls = _spy(monkeypatch)
    r = client.post("/kb/chat", json={"messages": [{"role": "user", "content": "Japan visa requirements"}], "model": model})
    assert r.status_code == 200, r.text
    text = calls[0]["kb_text"]
    assert "Web results (fetched just now)" in text and "[1]" in text
    assert NOTE_TEXT in text  # KB context still there, alongside
    # Privacy: the only outbound data is the query — never note text.
    ddg = [u for u in net if u.startswith(web_search.DDG_URL)]
    assert len(ddg) == 1
    q = urllib.parse.unquote_plus(ddg[0][len(web_search.DDG_URL):])
    assert q == "Japan visa requirements"
    assert all("zanzibarquokka" not in urllib.parse.unquote_plus(u) for u in net)


@pytest.mark.parametrize("model", ["claude-sonnet-5-5", "gpt-5-mini"])
def test_native_search_providers_get_no_block(client, net, monkeypatch, model):
    calls = _spy(monkeypatch)
    r = client.post("/kb/chat", json={"messages": [{"role": "user", "content": "Japan visa requirements"}], "model": model, "web": True})
    assert r.status_code == 200, r.text
    assert "Web results" not in calls[0]["kb_text"]
    assert net == []


def test_web_false_and_own_data_skip_network(client, net, monkeypatch):
    calls = _spy(monkeypatch)
    client.post("/kb/chat", json={"messages": [{"role": "user", "content": "Japan visa requirements"}], "model": "local:qwen3:8b", "web": False})
    client.post("/kb/chat", json={"messages": [{"role": "user", "content": "what's in my Japan trip notes"}], "model": "local:qwen3:8b"})
    assert net == [] and all("Web results" not in c["kb_text"] for c in calls)


# --- 2026-11-05 correction: API backends, DDG opt-in --------------------------


def test_no_backend_configured(monkeypatch):
    for k in ("QUINTACLE_WEB_SEARCH", "QUINTACLE_SEARXNG_URL", "QUINTACLE_BRAVE_API_KEY", "QUINTACLE_WEB_BACKEND"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(web_search.urllib.request, "urlopen", lambda *a, **k: pytest.fail("no network without a backend"))
    assert web_search.backend() is None
    assert web_search.chat_web_block("local", None, "latest news on the Austria visa") is None  # auto: silent
    notice = web_search.chat_web_block("local", True, "Austria visa requirements")
    assert notice and "unavailable" in notice


def test_brave_backend(monkeypatch):
    monkeypatch.delenv("QUINTACLE_SEARXNG_URL", raising=False)
    monkeypatch.setenv("QUINTACLE_BRAVE_API_KEY", "test-key")
    seen = {}

    class Resp:
        def __init__(self, body):
            self.body = body

        def read(self):
            return self.body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake(req, timeout=None):
        seen["url"] = req.full_url
        seen["token"] = req.get_header("X-subscription-token")
        return Resp(b'{"web":{"results":[{"title":"Belvedere","url":"https://www.belvedere.at/","description":"Open <b>daily</b> 9-18"}]}}')

    monkeypatch.setattr(web_search.urllib.request, "urlopen", fake)
    assert web_search.backend() == "brave"
    out = web_search.search("Belvedere opening hours")
    assert out == [{"title": "Belvedere", "url": "https://www.belvedere.at/", "snippet": "Open daily 9-18"}]
    assert seen["token"] == "test-key" and "api.search.brave.com" in seen["url"]
