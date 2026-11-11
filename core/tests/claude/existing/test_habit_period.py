"""2026-11-05: habit target_period is normalized/validated at write time."""
import pytest
from pydantic import ValidationError

from quintacle_core.nodes.logs.api import HabitCreate, HabitUpdate


@pytest.mark.parametrize("raw,want", [("weekly", "week"), ("Week", "week"), ("daily", "day"), ("bi-weekly", "2weeks"), ("2 weeks", "2weeks"), ("monthly", "month"), ("2weeks", "2weeks")])
def test_period_aliases(raw, want):
    assert HabitCreate(name="g", target_amount=3, target_period=raw).target_period == want
    assert HabitUpdate(target_period=raw).target_period == want


def test_bad_period_rejected_and_omitted_update_untouched():
    with pytest.raises(ValidationError):
        HabitCreate(name="g", target_amount=3, target_period="yearly")
    assert HabitUpdate().target_period is None
