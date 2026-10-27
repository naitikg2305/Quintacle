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
