"""Travel sorting + the place graph with the REAL local models — provider=local,
cloud blocked (a step that only works with Claude fails "cloud call blocked")."""
import pytest

from tests.claude import travel_cases


@pytest.mark.parametrize("check", travel_cases.ALL, ids=lambda f: f.__name__.removeprefix("check_"))
def test_travel_local(client, check):
    check(client, "local")
