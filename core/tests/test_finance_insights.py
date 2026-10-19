"""Deterministic finance analytics (next-wave-plan §1): every number below is
hand-computed from the seeded fixtures — the module must reproduce them
exactly, since no model is ever allowed to re-derive these."""
from datetime import date

from quintacle_core.db import connect
from quintacle_core.nodes.finance.insights import (
    detect_subscriptions,
    merchant_movers,
    merchant_rollup,
    monthly_breakdown,
)
from quintacle_core.nodes.logs.repository import LogsRepository

TODAY = date(2026, 10, 15)


def _repo(tmp_path) -> LogsRepository:
    return LogsRepository(connect(tmp_path / "test.db"))


def _seed(repo):
    # September: food 32.80 (2x Chipotle 12.80 + coffee 7.20), subscription 15.49, regular 1200
    repo.log_expense(date(2026, 9, 5), 12.80, "Chipotle", "dining", "", "food")
    repo.log_expense(date(2026, 9, 21), 12.80, "Chipotle", "dining", "", "food")
    repo.log_expense(date(2026, 9, 11), 7.20, "Blue Bottle", "coffee", "", "food")
    repo.log_expense(date(2026, 9, 2), 15.49, "Netflix", "", "", "subscription")
    repo.log_expense(date(2026, 9, 1), 1200.00, "Rent Co", "rent", "", "regular")
    # October (to the 15th): food 12.80, subscription 15.49, shopping 89.99
    repo.log_expense(date(2026, 10, 4), 12.80, "Chipotle", "dining", "", "food")
    repo.log_expense(date(2026, 10, 2), 15.49, "Netflix", "", "", "subscription")
    repo.log_expense(date(2026, 10, 9), 89.99, "Amazon", "", "", "shopping")
    # Income
    repo.log_income(date(2026, 9, 1), 4000.00, "Acme", "salary")
    repo.log_income(date(2026, 10, 1), 4000.00, "Acme", "salary")
    repo.log_income(date(2026, 10, 10), 250.00, "eBay sale", "other")


def test_monthly_breakdown_totals_kinds_and_savings(tmp_path):
    repo = _repo(tmp_path)
    _seed(repo)

    months = monthly_breakdown(repo.conn, months=2, today=TODAY)

    assert [m["month"] for m in months] == ["2026-09", "2026-10"]
    sept, octo = months
    assert sept["by_kind"]["food"] == 32.80
    assert sept["by_kind"]["subscription"] == 15.49
    assert sept["by_kind"]["regular"] == 1200.00
    assert sept["total"] == round(32.80 + 15.49 + 1200.00, 2)
    assert sept["income"] == 4000.00
    assert sept["savings"] == round(4000.00 - sept["total"], 2)
    assert sept["savings_rate_pct"] == round(sept["savings"] / 4000.00 * 100, 1)
    assert sept["delta_total"] is None  # no previous month in range

    assert octo["total"] == round(12.80 + 15.49 + 89.99, 2)
    assert octo["income"] == 4250.00
    assert octo["delta_total"] == round(octo["total"] - sept["total"], 2)
    assert octo["delta_by_kind"]["food"] == round(12.80 - 32.80, 2)
    assert octo["delta_by_kind"]["shopping"] == 89.99


def test_monthly_breakdown_zero_income_month_has_null_rate(tmp_path):
    repo = _repo(tmp_path)
    repo.log_expense(date(2026, 10, 2), 10.0, "X", "", "", "regular")

    months = monthly_breakdown(repo.conn, months=1, today=TODAY)

    assert months[0]["income"] == 0.0
    assert months[0]["savings"] == -10.0
    assert months[0]["savings_rate_pct"] is None


def test_merchant_rollup_counts_totals_and_order(tmp_path):
    repo = _repo(tmp_path)
    _seed(repo)

    rollup = merchant_rollup(repo.conn, date(2026, 9, 1), date(2026, 10, 15))

    by_name = {r["merchant"]: r for r in rollup}
    assert by_name["Chipotle"]["count"] == 3
    assert by_name["Chipotle"]["total"] == round(12.80 * 3, 2)
    assert by_name["Chipotle"]["average"] == 12.80
    assert by_name["Chipotle"]["last_date"] == "2026-10-04"
    assert rollup[0]["merchant"] == "Rent Co"  # biggest total first


def test_merchant_movers_this_month_vs_last(tmp_path):
    repo = _repo(tmp_path)
    _seed(repo)

    movers = merchant_movers(repo.conn, today=TODAY)

    by_name = {m["merchant"]: m for m in movers}
    assert by_name["Rent Co"]["delta"] == -1200.00  # charged in Sept, not yet in Oct
    assert by_name["Amazon"]["delta"] == 89.99
    assert by_name["Chipotle"]["delta"] == round(12.80 - 25.60, 2)
    assert movers[0]["merchant"] == "Rent Co"  # largest absolute swing first


def test_subscription_detection_monthly_cadence(tmp_path):
    repo = _repo(tmp_path)
    for d in (date(2026, 8, 2), date(2026, 9, 2), date(2026, 10, 2)):
        repo.log_expense(d, 15.49, "Netflix", "", "", "subscription")
    # Same merchant, wildly different amounts at no cadence — not a subscription.
    repo.log_expense(date(2026, 9, 5), 23.10, "Chipotle", "", "", "food")
    repo.log_expense(date(2026, 9, 7), 61.75, "Chipotle", "", "", "food")

    result = detect_subscriptions(repo.conn, today=TODAY)

    assert len(result["subscriptions"]) == 1
    sub = result["subscriptions"][0]
    assert sub["merchant"] == "Netflix"
    assert sub["cadence"] == "monthly"
    assert sub["charges"] == 3
    assert sub["amount"] == 15.49
    assert sub["active"] is True
    # gaps 31 and 30 days -> median 30.5, rounded to 30 -> Oct 2 + 30 days
    assert sub["next_expected"] == "2026-11-01"
    assert result["monthly_burn"] == 15.49


def test_subscription_detection_tolerates_small_price_change(tmp_path):
    repo = _repo(tmp_path)
    repo.log_expense(date(2026, 8, 10), 9.99, "Spotify", "", "", "regular")
    repo.log_expense(date(2026, 9, 10), 10.49, "Spotify", "", "", "regular")  # within $1
    repo.log_expense(date(2026, 10, 10), 10.49, "Spotify", "", "", "regular")

    result = detect_subscriptions(repo.conn, today=TODAY)

    assert [s["merchant"] for s in result["subscriptions"]] == ["Spotify"]
    assert result["subscriptions"][0]["kind_already_subscription"] is False


def test_lapsed_subscription_not_counted_in_burn(tmp_path):
    repo = _repo(tmp_path)
    repo.log_expense(date(2026, 1, 3), 12.00, "OldBox", "", "", "subscription")
    repo.log_expense(date(2026, 2, 3), 12.00, "OldBox", "", "", "subscription")
    repo.log_expense(date(2026, 3, 3), 12.00, "OldBox", "", "", "subscription")

    result = detect_subscriptions(repo.conn, today=TODAY)

    assert len(result["subscriptions"]) == 1
    assert result["subscriptions"][0]["active"] is False
    assert result["monthly_burn"] == 0.0
