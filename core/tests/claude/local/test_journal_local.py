"""Journal parsing + the Day view with the REAL local model — provider=local,
cloud blocked; every parse must have been answered locally."""
import pytest

from tests.claude import journal_cases


@pytest.mark.parametrize("check", journal_cases.ALL, ids=lambda f: f.__name__.removeprefix("check_"))
def test_local(client, check):
    for r in check(client, "local"):
        assert r.get("provider_used") == "local", f"provider_used={r.get('provider_used')!r}"
