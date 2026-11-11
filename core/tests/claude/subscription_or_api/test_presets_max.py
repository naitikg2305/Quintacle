"""Presets (routine / ingredient / meal) with REAL Claude via Max —
provider=cloud; every model-backed check proves a Max call actually happened
(the user chose cloud: a silent local answer is wrong, API spend is blocked)."""
import pytest

from tests.claude import presets_cases
from tests.claude.harness import MAX_CALLS


@pytest.mark.parametrize("check", presets_cases.ALL, ids=lambda f: f.__name__.removeprefix("check_"))
def test_max(client, check):
    before = len(MAX_CALLS)
    check(client, "cloud")
    if check not in presets_cases.DETERMINISTIC:
        assert len(MAX_CALLS) > before, "Claude (Max) was never called"
