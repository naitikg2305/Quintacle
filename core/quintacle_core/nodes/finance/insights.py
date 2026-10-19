"""Deterministic spend/income analytics (next-wave-plan §1, decided 2026-10-19).

Everything in this module is SQL + plain arithmetic over expense_log /
income_log — zero model calls, by principle: models never re-derive what
SQLite already knows. The API layer hands these finished numbers straight to
the frontend (and, one day, to a model as *finished* context).

All date math is Eastern (clock.today()); months are calendar months keyed
"YYYY-MM".
"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from statistics import median

from ... import clock

EXPENSE_KINDS = ["subscription", "food", "alcohol", "experience", "shopping", "big_purchase", "regular"]


def _month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    idx = year * 12 + (month - 1) + delta
    return idx // 12, idx % 12 + 1


def _last_months(today: date, months: int) -> list[str]:
    """The last `months` calendar months ending with the current one, oldest
    first — e.g. months=3 in October -> ["2026-08", "2026-09", "2026-10"]."""
    keys = []
    for i in range(months - 1, -1, -1):
        y, m = _shift_month(today.year, today.month, -i)
        keys.append(f"{y:04d}-{m:02d}")
    return keys


def monthly_breakdown(conn: sqlite3.Connection, months: int = 12, today: date | None = None) -> list[dict]:
    """Per-month totals by kind + income + savings rate + month-over-month
    deltas, oldest first. Savings rate = (income - spend) / income, as a
    percentage, null for months with no income (division by zero is not a
    model's problem to hand-wave — it's just null)."""
    today = today or clock.today()
    keys = _last_months(today, months)
    start = f"{keys[0]}-01"

    spend_by_month_kind: dict[str, dict[str, float]] = {}
    totals: dict[str, float] = {}
    for row in conn.execute(
        """SELECT substr(date, 1, 7) AS month, kind, SUM(amount) AS total
           FROM expense_log WHERE date >= ? GROUP BY month, kind""",
        (start,),
    ):
        spend_by_month_kind.setdefault(row["month"], {})[row["kind"]] = round(row["total"], 2)
        totals[row["month"]] = totals.get(row["month"], 0.0) + row["total"]

    income_by_month: dict[str, float] = {
        row["month"]: round(row["total"], 2)
        for row in conn.execute(
            """SELECT substr(date, 1, 7) AS month, SUM(amount) AS total
               FROM income_log WHERE date >= ? GROUP BY month""",
            (start,),
        )
    }

    result = []
    prev: dict | None = None
    for key in keys:
        by_kind = {kind: spend_by_month_kind.get(key, {}).get(kind, 0.0) for kind in EXPENSE_KINDS}
        total = round(totals.get(key, 0.0), 2)
        income = income_by_month.get(key, 0.0)
        savings = round(income - total, 2)
        month = {
            "month": key,
            "total": total,
            "by_kind": by_kind,
            "income": income,
            "savings": savings,
            "savings_rate_pct": round(savings / income * 100, 1) if income > 0 else None,
            "delta_total": round(total - prev["total"], 2) if prev is not None else None,
            "delta_by_kind": (
                {kind: round(by_kind[kind] - prev["by_kind"][kind], 2) for kind in EXPENSE_KINDS}
                if prev is not None
                else None
            ),
        }
        result.append(month)
        prev = month
    return result


def merchant_rollup(conn: sqlite3.Connection, start: date, end: date, limit: int = 25) -> list[dict]:
    """Who actually gets the money: per-merchant count/total/average/last
    charge in the window, biggest total first. Merchants are grouped
    case/whitespace-insensitively; blank merchants pool under (unspecified)."""
    rows = conn.execute(
        """SELECT LOWER(TRIM(merchant)) AS key,
                  MAX(TRIM(merchant)) AS merchant,
                  COUNT(*) AS count,
                  SUM(amount) AS total,
                  MAX(date) AS last_date
           FROM expense_log
           WHERE date >= ? AND date <= ?
           GROUP BY key
           ORDER BY total DESC
           LIMIT ?""",
        (start.isoformat(), end.isoformat(), limit),
    ).fetchall()
    return [
        {
            "merchant": r["merchant"] or "(unspecified)",
            "count": r["count"],
            "total": round(r["total"], 2),
            "average": round(r["total"] / r["count"], 2),
            "last_date": r["last_date"],
        }
        for r in rows
    ]


def merchant_movers(conn: sqlite3.Connection, today: date | None = None, limit: int = 10) -> list[dict]:
    """Biggest movers, this month vs last: per-merchant delta of month-to-date
    totals, largest absolute swing first."""
    today = today or clock.today()
    this_key = _month_key(today)
    py, pm = _shift_month(today.year, today.month, -1)
    prev_key = f"{py:04d}-{pm:02d}"

    def month_totals(key: str) -> dict[str, tuple[str, float]]:
        out: dict[str, tuple[str, float]] = {}
        for r in conn.execute(
            """SELECT LOWER(TRIM(merchant)) AS k, MAX(TRIM(merchant)) AS merchant, SUM(amount) AS total
               FROM expense_log WHERE substr(date, 1, 7) = ? GROUP BY k""",
            (key,),
        ):
            out[r["k"]] = (r["merchant"] or "(unspecified)", r["total"])
        return out

    current, previous = month_totals(this_key), month_totals(prev_key)
    movers = []
    for k in set(current) | set(previous):
        label = (current.get(k) or previous.get(k))[0]
        cur = current.get(k, (label, 0.0))[1]
        prev = previous.get(k, (label, 0.0))[1]
        movers.append(
            {
                "merchant": label,
                "this_month": round(cur, 2),
                "last_month": round(prev, 2),
                "delta": round(cur - prev, 2),
            }
        )
    movers.sort(key=lambda m: abs(m["delta"]), reverse=True)
    return movers[:limit]


# Subscription recurrence (next-wave-plan §2b "bonus unlock"): same merchant +
# similar amount at a steady cadence is arithmetic, not AI. Tolerances below
# are deliberate constants, not tunables-by-model.
_AMOUNT_TOLERANCE_ABS = 1.0  # dollars
_AMOUNT_TOLERANCE_PCT = 0.05
_CADENCES = [  # (label, min median gap days, max median gap days, charges per month)
    ("weekly", 5, 9, 52 / 12),
    ("monthly", 26, 36, 1.0),
    ("yearly", 350, 380, 1 / 12),
]


def _similar_amount(a: float, b: float) -> bool:
    return abs(a - b) <= max(_AMOUNT_TOLERANCE_ABS, _AMOUNT_TOLERANCE_PCT * max(abs(a), abs(b)))


def detect_subscriptions(conn: sqlite3.Connection, today: date | None = None, lookback_days: int = 400) -> dict:
    """Recurring-charge detection over ALL expenses (not just kind=
    subscription — mis-kinded Netflix rows still recur): group by merchant,
    cluster similar amounts, and call a cluster recurring when it has >= 2
    charges whose median gap fits a known cadence. Returns the detected
    lines plus the total monthly burn of the ones still active (next
    expected charge not overdue by more than half an interval)."""
    today = today or clock.today()
    start = (today - timedelta(days=lookback_days)).isoformat()
    rows = conn.execute(
        """SELECT date, amount, TRIM(merchant) AS merchant, kind FROM expense_log
           WHERE date >= ? AND TRIM(merchant) != '' ORDER BY date, id""",
        (start,),
    ).fetchall()

    by_merchant: dict[str, list[sqlite3.Row]] = {}
    for r in rows:
        by_merchant.setdefault(r["merchant"].lower(), []).append(r)

    detected = []
    for charges in by_merchant.values():
        # Cluster by amount: each charge joins the first cluster whose mean it
        # sits within tolerance of, else starts a new one.
        clusters: list[list[sqlite3.Row]] = []
        for charge in charges:
            for cluster in clusters:
                mean = sum(c["amount"] for c in cluster) / len(cluster)
                if _similar_amount(charge["amount"], mean):
                    cluster.append(charge)
                    break
            else:
                clusters.append([charge])

        for cluster in clusters:
            if len(cluster) < 2:
                continue
            dates = [date.fromisoformat(c["date"]) for c in cluster]
            gaps = [(b - a).days for a, b in zip(dates, dates[1:])]
            med = median(gaps)
            cadence = next((c for c in _CADENCES if c[1] <= med <= c[2]), None)
            if cadence is None:
                continue
            label, _, _, per_month = cadence
            avg_amount = round(sum(c["amount"] for c in cluster) / len(cluster), 2)
            next_expected = dates[-1] + timedelta(days=round(med))
            active = (today - next_expected).days <= med / 2
            detected.append(
                {
                    "merchant": cluster[0]["merchant"],
                    "amount": avg_amount,
                    "cadence": label,
                    "charges": len(cluster),
                    "first_date": dates[0].isoformat(),
                    "last_date": dates[-1].isoformat(),
                    "next_expected": next_expected.isoformat(),
                    "active": active,
                    "monthly_equivalent": round(avg_amount * per_month, 2),
                    "kind_already_subscription": all(c["kind"] == "subscription" for c in cluster),
                }
            )

    detected.sort(key=lambda s: s["monthly_equivalent"], reverse=True)
    monthly_burn = round(sum(s["monthly_equivalent"] for s in detected if s["active"]), 2)
    return {"subscriptions": detected, "monthly_burn": monthly_burn}
