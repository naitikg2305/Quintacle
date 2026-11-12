import os
import tempfile

import pytest

# 2026-11-11: api.py builds its app at IMPORT time (`app = create_app()`), and
# that startup runs real writes — the graph-capture backfill and the stale-
# reference cleanup (maintenance.py). Without this, merely importing api in a
# test pointed them at the owner's real ~/.quintacle. Force a throwaway data
# dir before any test module imports quintacle_core (tests that need a store
# still monkeypatch api.DATA_DIR / pass tmp_path as before).
os.environ["QUINTACLE_DATA_DIR"] = tempfile.mkdtemp(prefix="quintacle-test-data-")


@pytest.fixture(autouse=True)
def _deterministic_prose_summaries(monkeypatch):
    """Retrieval-index prose one-liners must use the deterministic fallback
    in ALL tests (retrieval.prose_summary): with QUINTACLE_SUMMARY_PROVIDER
    unset, a dev machine with Ollama running would otherwise make a real
    local-model call from every KB/journal write hook — slow, and model
    output is never valid test evidence (CLAUDE.md's model-quality rule).
    Tests that exercise the model seam itself monkeypatch past this."""
    monkeypatch.setenv("QUINTACLE_SUMMARY_PROVIDER", "off")
    # Same determinism for the vector lane: with sqlite-vec installed and
    # Ollama up (a dev machine after the real-data backfill), live embeddings
    # would otherwise join FTS results and reshuffle rankings mid-suite.
    monkeypatch.setenv("QUINTACLE_VECTOR_LANE", "off")
    # Soft-record fact extraction (soft_record.extract_facts) is a local-model
    # call kicked off after every kept transcript archive; off suite-wide so a
    # dev machine's Ollama is never hit. Tests monkeypatch the extractor.
    monkeypatch.setenv("QUINTACLE_SOFT_RECORD_PROVIDER", "off")
    # Claude Max (max_backend.py) shells out to the real `claude` CLI and
    # spends subscription usage — never from a test. With it disabled every
    # cloud_client() call goes straight to the (faked) Anthropic client, so
    # existing anthropic fakes keep working. Max's own tests re-enable it
    # with a fake CLI binary.
    monkeypatch.setenv("QUINTACLE_DISABLE_MAX", "1")
    # Web lane (web_search.py) for local/Bedrock chat: never a real network
    # call from a test. test_web_search.py re-enables it with stubbed urlopen.
    monkeypatch.setenv("QUINTACLE_WEB_SEARCH", "off")
    # USDA nutrition db (nutrition_db/): never the owner's real installed
    # db, and the candidate picker never calls a model. Tests that need a
    # db build one from tests/claude/existing/fixtures/usda and point QUINTACLE_USDA_DB at it.
    monkeypatch.setenv("QUINTACLE_USDA_DB", "/nonexistent/quintacle-test/usda.db")
    monkeypatch.setenv("QUINTACLE_USDA_PICK_PROVIDER", "off")
    # Offline geocoder (geo_offline.py, 2026-11-11): never the owner's real
    # installed GeoNames data — tests that need a gazetteer build a tiny one.
    monkeypatch.setenv("QUINTACLE_GEONAMES_DIR", "/nonexistent/quintacle-test/geonames")
    # Local-first image pipeline (2026-11-06, perception/image_policy.py):
    # never a real OCR engine (this machine has tesseract on PATH), never a
    # real YOLO run (weights download on first use), never a real local VLM.
    # Tests stub each stage explicitly.
    monkeypatch.setenv("QUINTACLE_OCR_BACKEND", "off")
    monkeypatch.setenv("QUINTACLE_IMAGE_TAGS", "off")
    monkeypatch.setenv("QUINTACLE_VISION_BACKEND", "off")
    from quintacle_core.perception import ocr as _ocr

    _ocr.clear_cache()


@pytest.fixture(autouse=True)
def _never_a_real_local_model(monkeypatch):
    """2026-11-11: a faked test must never reach the real Ollama — an
    unstubbed call used to queue behind the GPU and hang the suite. Blocks
    the network hop to the Ollama port only; tests that stub urlopen or
    _parse_local themselves (after this fixture) still win."""
    import urllib.parse
    import urllib.request

    real = urllib.request.urlopen

    def guarded(req, *a, **k):
        url = str(getattr(req, "full_url", req))
        if ":11434" in url:
            raise OSError("real local-model call in a faked test — stub it")
        # 2026-11-12: no internet either. Since the sandboxed data dir above
        # (no cached weights), the first photo commit tried to download the
        # YOLO weights from GitHub and sat out the 120 s timeout (suite went
        # ~1.5 → ~3.7 min). Fail fast instead; perception degrades gracefully.
        host = urllib.parse.urlsplit(url).hostname or ""
        if host and host not in ("localhost", "127.0.0.1", "::1", "testserver"):
            raise OSError(f"real network call in a faked test ({host}) — stub it")
        return real(req, *a, **k)

    monkeypatch.setattr(urllib.request, "urlopen", guarded)


@pytest.fixture(autouse=True)
def _never_the_metered_api(monkeypatch):
    """2026-11-12: a faked test must never reach the real Anthropic API.
    api.py's load_dotenv() puts the owner's real key into the environment, so
    an unstubbed cloud seam (max_backend's API fallback) made real, billed
    calls — test_drop_presets did, ~3 per suite run, via the meal composer's
    micro estimate. Replace the key and refuse any non-local httpx request
    (the SDK's transport). Tests that fake anthropic.Anthropic never get here."""
    import httpx

    monkeypatch.setenv("ANTHROPIC_API_KEY", "faked-tests-never-call-the-api")
    real_send = httpx.Client.send

    def guarded_send(self, request, *a, **k):
        host = request.url.host or ""
        if host not in ("localhost", "127.0.0.1", "::1", "testserver"):
            raise httpx.ConnectError(f"real network call in a faked test ({host}) — stub it", request=request)
        return real_send(self, request, *a, **k)

    monkeypatch.setattr(httpx.Client, "send", guarded_send)
