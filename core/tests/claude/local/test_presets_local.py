"""Presets (routine / ingredient / meal) with the REAL local models —
provider=local, cloud blocked (a cloud-only step fails as "cloud call blocked")."""
import pytest

from tests.claude import presets_cases


@pytest.mark.parametrize("check", presets_cases.ALL, ids=lambda f: f.__name__.removeprefix("check_"))
def test_local(client, check):
    check(client, "local")
