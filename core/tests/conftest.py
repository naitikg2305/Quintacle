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
