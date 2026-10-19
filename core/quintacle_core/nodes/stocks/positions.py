"""Positions / cost basis / P&L — pure deterministic arithmetic over
transaction rows, computed fresh on every read and never stored anywhere
(docs/next-wave-plan.md §2: "cost basis and realized P&L computed, never
hand-maintained"; architecture principle: anything arithmetic is computed in
code and handed to models/pages as finished numbers).

Lot accounting is FIFO: each buy opens a lot (its fees folded into that
lot's cost); each sell consumes the oldest lots first. Realized P&L on a
sell = proceeds − consumed lot cost − sell fees. Dividends are cash income,
tracked per symbol, never touching share count or basis. A sell of more
shares than the lots hold consumes what exists (the excess shares realize
their full proceeds, zero basis) and flags the position `oversold` — a
visible data-entry error, not a crash and not silently-wrong math.
"""
from __future__ import annotations


def compute_positions(transactions: list[dict], latest_price_by_symbol: dict[str, dict] | None = None) -> dict:
    """`transactions`: ledger rows (dicts with date/action/symbol/qty/price/
    fees), any order — sorted here by (date, id) so intraday order follows
    entry order. `latest_price_by_symbol`: newest snapshot row per symbol
    ({symbol: {"price", "price_date", "source", ...}}), or None/missing
    symbols for "no snapshot yet" — unrealized P&L and market value then stay
    None (graceful offline: the caller shows whatever stale date it has).

    Returns {"positions": [per-symbol dicts, open first then closed, A→Z],
    "totals": {...}} — every number a finished, code-derived fact."""
    latest_price_by_symbol = latest_price_by_symbol or {}
    rows = sorted(transactions, key=lambda r: (r["date"], r.get("id") or 0))

    by_symbol: dict[str, dict] = {}
    lots: dict[str, list[dict]] = {}
    for row in rows:
        symbol = row["symbol"]
        state = by_symbol.setdefault(
            symbol,
            {
                "symbol": symbol,
                "realized_pnl": 0.0,
                "dividends": 0.0,
                "buy_count": 0,
                "sell_count": 0,
                "oversold": False,
                "accounts": [],
                "first_date": row["date"],
                "last_date": row["date"],
            },
        )
        state["last_date"] = row["date"]
        account = (row.get("account") or "").strip()
        if account and account not in state["accounts"]:
            state["accounts"].append(account)

        action = row["action"]
        qty = float(row.get("qty") or 0)
        price = float(row.get("price") or 0)
        fees = float(row.get("fees") or 0)

        if action == "buy":
            lots.setdefault(symbol, []).append({"qty": qty, "cost": qty * price + fees})
            state["buy_count"] += 1
        elif action == "sell":
            state["sell_count"] += 1
            remaining = qty
            consumed_cost = 0.0
            symbol_lots = lots.setdefault(symbol, [])
            while remaining > 1e-9 and symbol_lots:
                lot = symbol_lots[0]
                take = min(lot["qty"], remaining)
                cost_share = lot["cost"] * (take / lot["qty"])
                consumed_cost += cost_share
                lot["qty"] -= take
                lot["cost"] -= cost_share
                remaining -= take
                if lot["qty"] <= 1e-9:
                    symbol_lots.pop(0)
            if remaining > 1e-9:
                state["oversold"] = True  # excess shares realize full proceeds, zero basis
            state["realized_pnl"] += qty * price - consumed_cost - fees
        elif action == "dividend":
            # `price` carries the TOTAL cash received (store.py's row semantics).
            state["dividends"] += price

    positions = []
    totals = {
        "cost_basis": 0.0,
        "market_value": 0.0,
        "unrealized_pnl": 0.0,
        "realized_pnl": 0.0,
        "dividends": 0.0,
        "priced_symbols": 0,
        "unpriced_symbols": 0,
    }
    for symbol, state in by_symbol.items():
        open_lots = lots.get(symbol, [])
        qty_held = sum(lot["qty"] for lot in open_lots)
        cost_basis = sum(lot["cost"] for lot in open_lots)
        snapshot = latest_price_by_symbol.get(symbol)

        position = {
            **state,
            "qty": round(qty_held, 6),
            "cost_basis": round(cost_basis, 2),
            "avg_cost": round(cost_basis / qty_held, 4) if qty_held > 1e-9 else None,
            "realized_pnl": round(state["realized_pnl"], 2),
            "dividends": round(state["dividends"], 2),
            "last_price": None,
            "last_price_date": None,
            "price_source": None,
            "market_value": None,
            "unrealized_pnl": None,
        }
        if snapshot is not None:
            position["last_price"] = snapshot["price"]
            position["last_price_date"] = snapshot["price_date"]
            position["price_source"] = snapshot.get("source")
            if qty_held > 1e-9:
                position["market_value"] = round(qty_held * snapshot["price"], 2)
                position["unrealized_pnl"] = round(qty_held * snapshot["price"] - cost_basis, 2)
        positions.append(position)

        totals["cost_basis"] += cost_basis
        totals["realized_pnl"] += state["realized_pnl"]
        totals["dividends"] += state["dividends"]
        if position["market_value"] is not None:
            totals["market_value"] += position["market_value"]
            totals["unrealized_pnl"] += position["unrealized_pnl"]
            totals["priced_symbols"] += 1
        elif qty_held > 1e-9:
            totals["unpriced_symbols"] += 1

    for key in ("cost_basis", "market_value", "unrealized_pnl", "realized_pnl", "dividends"):
        totals[key] = round(totals[key], 2)

    # Open positions first (largest cost basis down), then closed ones, A→Z within each.
    positions.sort(key=lambda p: (p["qty"] <= 1e-9, -(p["cost_basis"] or 0), p["symbol"]))
    return {"positions": positions, "totals": totals}
