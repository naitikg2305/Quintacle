"""Wardrobe / grooming / home drops with the REAL local models — provider=local,
cloud blocked, registries seeded (lifestyle_cases.seed)."""
import pytest

from tests.claude import lifestyle_cases


@pytest.fixture(scope="module", autouse=True)
def _seeded(client):
    lifestyle_cases.seed(client)


@pytest.mark.parametrize("check", lifestyle_cases.ALL, ids=lambda f: f.__name__.removeprefix("check_"))
def test_lifestyle_local(client, check):
    r = check(client, "local")
    if check in lifestyle_cases.IMAGE_CHECKS:
        assert r.get("pipeline") != "cloud"  # local-first: the photo was read on this machine
