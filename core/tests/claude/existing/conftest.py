import pytest


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
    import urllib.request

    real = urllib.request.urlopen

    def guarded(req, *a, **k):
        url = getattr(req, "full_url", req)
        if ":11434" in str(url):
            raise OSError("real local-model call in a faked test — stub it")
        return real(req, *a, **k)

    monkeypatch.setattr(urllib.request, "urlopen", guarded)
