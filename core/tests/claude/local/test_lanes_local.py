"""Background model lanes with the REAL local models (qwen3:8b + embeddinggemma
via Ollama), cloud blocked — prose_summary, vector retrieval, soft-record
fact extraction, and the code web lane for local chat. Each check switches
its own lane back on (the harness forces them all off)."""
import pytest

from tests.claude import lanes_cases


@pytest.mark.parametrize("check", lanes_cases.ALL, ids=lambda f: f.__name__.removeprefix("check_"))
def test_lanes_local(client, check):
    check(client, "local")
