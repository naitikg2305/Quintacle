"""Wardrobe / grooming / home drops with REAL Claude via Max — provider=cloud;
each test proves a Max call actually happened (no silent local answer, no API
spend). Registries seeded (lifestyle_cases.seed)."""
import pytest

from tests.claude import lifestyle_cases
from tests.claude.harness import MAX_CALLS


@pytest.fixture(scope="module", autouse=True)
def _seeded(client):
    lifestyle_cases.seed(client)


@pytest.mark.parametrize("check", lifestyle_cases.ALL, ids=lambda f: f.__name__.removeprefix("check_"))
def test_lifestyle_max(client, check):
    before = len(MAX_CALLS)
    check(client, "cloud")
    assert len(MAX_CALLS) > before, "Claude (Max) was never called"
