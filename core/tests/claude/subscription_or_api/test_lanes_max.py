"""Background model lanes with cloud (Max) ENABLED. The summary, embedding
and soft-record lanes are pinned local, so here each check proves they
still run on Ollama and never touch Claude; the web check proves Max chat
answers a fresh-fact question with a cited URL via its NATIVE search, never
the code web lane. Max is only called by the web check (it asserts that)."""
import pytest

from tests.claude import lanes_cases


@pytest.mark.parametrize("check", lanes_cases.ALL, ids=lambda f: f.__name__.removeprefix("check_"))
def test_lanes_max(client, check):
    check(client, "cloud")
