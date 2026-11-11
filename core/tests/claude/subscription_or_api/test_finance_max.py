"""Finance text + statement drops with REAL Claude via Max — provider=cloud.
Model checks prove a Max call actually happened (no silent local answer, no
API spend); deterministic checks (CSV by extension, "income:" prefix) prove
Claude was NOT called, because code alone must handle them."""
import pytest

from tests.claude import finance_cases
from tests.claude.harness import MAX_CALLS

_ids = lambda f: f.__name__.removeprefix("check_")  # noqa: E731


@pytest.mark.parametrize("check", finance_cases.MODEL_CHECKS, ids=_ids)
def test_max(client, check):
    before = len(MAX_CALLS)
    check(client, "cloud")
    assert len(MAX_CALLS) > before, "Claude (Max) was never called"


@pytest.mark.parametrize("check", finance_cases.DETERMINISTIC_CHECKS, ids=_ids)
def test_max_deterministic(client, check):
    before = len(MAX_CALLS)
    check(client, "cloud")
    assert len(MAX_CALLS) == before, "a deterministic drop shelled out to Claude"
