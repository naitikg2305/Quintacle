"""KB chat with REAL Claude via Max (max:haiku) — each test proves a Max call
actually happened; the private-note checks prove the secret never reached it."""
import pytest

from tests.claude import chat_cases
from tests.claude.harness import MAX_CALLS


@pytest.mark.parametrize("check", chat_cases.ALL, ids=lambda f: f.__name__.removeprefix("check_"))
def test_chat_max(client, check):
    before = len(MAX_CALLS)
    check(client, "cloud")
    assert len(MAX_CALLS) > before, "Claude (Max) was never called"
