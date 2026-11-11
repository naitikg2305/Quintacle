"""Journal parsing + the Day view with REAL Claude via Max — provider=cloud;
each test proves Claude answered (provider_used == "cloud", Max calls counted,
the metered API blocked)."""
import pytest

from tests.claude import journal_cases
from tests.claude.harness import MAX_CALLS


@pytest.mark.parametrize("check", journal_cases.ALL, ids=lambda f: f.__name__.removeprefix("check_"))
def test_max(client, check):
    before = len(MAX_CALLS)
    responses = check(client, "cloud")
    for r in responses:
        assert r.get("provider_used") == "cloud", f"provider_used={r.get('provider_used')!r}"
    # Full-day checks share one cached parse, so only the first one calls Max;
    # the rest still require that Max has answered at least once.
    assert MAX_CALLS and (len(MAX_CALLS) > before or check in _CACHED), "Claude (Max) was never called"


_CACHED = {f for f in journal_cases.ALL if f.__name__.startswith("check_full_day_")}
