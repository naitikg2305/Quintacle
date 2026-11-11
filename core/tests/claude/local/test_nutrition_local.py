"""Nutrition with the REAL local models — provider=local, cloud blocked.
USDA matching is real (the harness copies the owner's usda.db)."""
import pytest

from tests.claude import nutrition_cases


@pytest.mark.parametrize("check", nutrition_cases.ALL, ids=lambda f: f.__name__.removeprefix("check_"))
def test_local(client, check):
    check(client, "local")
