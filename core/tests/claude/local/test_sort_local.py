"""Sorting with the REAL local models — provider=local, cloud blocked."""
import pytest

from tests.claude import sort_cases


@pytest.mark.parametrize("check", sort_cases.ALL, ids=lambda f: f.__name__.removeprefix("check_"))
def test_local(client, check):
    r = check(client, "local")
    if check is sort_cases.check_label_photo:
        assert r.get("pipeline") != "cloud"
