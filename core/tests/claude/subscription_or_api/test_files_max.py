"""File drops beyond plain PDFs with REAL Claude via Max — provider=cloud;
each test proves a Max call actually happened (no silent local answer, no
metered-API spend)."""
import pytest

from tests.claude import files_cases
from tests.claude.harness import MAX_CALLS


@pytest.mark.parametrize("check", files_cases.ALL, ids=lambda f: f.__name__.removeprefix("check_"))
def test_max(client, check):
    before = len(MAX_CALLS)
    check(client, "cloud")
    assert len(MAX_CALLS) > before, "Claude (Max) was never called"
