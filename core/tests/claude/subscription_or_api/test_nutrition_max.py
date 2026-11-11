"""Nutrition with REAL Claude via Max — provider=cloud; every model-driven
check proves a Max call actually happened (no silent local answer, no API
spend). The USDA numbers themselves must still come from the db."""
import pytest

from tests.claude import nutrition_cases
from tests.claude.harness import MAX_CALLS


@pytest.mark.parametrize("check", nutrition_cases.ALL, ids=lambda f: f.__name__.removeprefix("check_"))
def test_max(client, check):
    before = len(MAX_CALLS)
    check(client, "cloud")
    if check not in nutrition_cases.NO_CLOUD_CALL:
        assert len(MAX_CALLS) > before, "Claude (Max) was never called"
