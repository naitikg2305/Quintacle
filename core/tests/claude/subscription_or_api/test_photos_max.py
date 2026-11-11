"""PHOTO drops with REAL Claude via Max — provider=cloud; each test proves a
Max call actually happened (no silent local answer, no API spend) and that
the image pipeline badge says "cloud"."""
import pytest

from tests.claude import photos_cases
from tests.claude.harness import MAX_CALLS


@pytest.mark.parametrize("check", photos_cases.ALL, ids=lambda f: f.__name__.removeprefix("check_"))
def test_max(client, check):
    before = len(MAX_CALLS)
    r = check(client, "cloud")
    assert len(MAX_CALLS) > before, "Claude (Max) was never called"
    assert r.get("pipeline") == "cloud", f"provider=cloud must read the photo with Claude: pipeline={r.get('pipeline')!r}"
