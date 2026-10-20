"""Text → stock-ledger transaction parse for the drop lane (next-wave-plan
§8: "stock:" prefix, plus the cheap natural-text gate in drop_router.py,
proposes a REAL ledger row — review → POST /stocks/transactions — replacing
the old static investment-entry lane)."""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel

from ... import clock
from ...llm_dispatch import parse_structured


class StockTransactionEstimate(BaseModel):
    """Mirrors StockTransactionStore.write()'s uniform row columns (see
    store.py's row-semantics docstring) plus entry_date/notes — the estimate
    is reviewed and committed straight to POST /stocks/transactions."""

    action: Literal["buy", "sell", "dividend"] = "buy"
    symbol: str = ""
    qty: float = 0
    price: float = 0
    fees: float = 0
    account: str = ""
    entry_date: str | None = None  # YYYY-MM-DD; relative words resolve against the reference date
    notes: str = ""


_SYSTEM_PROMPT = (
    "Structure this into one stock-ledger transaction: action (buy, sell, or dividend), symbol "
    "(the ticker, e.g. \"AAPL\" — uppercase; infer it from a well-known company name if only the "
    "name is given), qty (number of shares), price (dollars PER SHARE for a buy/sell), fees "
    "(commission/fees in dollars if stated, else 0), account (the brokerage/account if stated), "
    "entry_date (YYYY-MM-DD if a date is stated), and notes (anything else worth remembering — "
    "why, strategy, context). Dividend semantics: for action=dividend, price is the TOTAL cash "
    "received (a dividend has no per-share meaning worth hand-entering) and qty stays 0 — the "
    "share count never changes. Do not invent numbers that aren't stated; leave them 0."
)


def structure_stock_transaction(
    description: str, reference_date: date | None = None, provider: str | None = None
) -> StockTransactionEstimate:
    """For the explicit "stock:"/"invest:" prefix (and the conservative
    unprefixed gate, drop_router.looks_like_stock_transaction) — intent
    already stated/matched, so no relevance gate, always extracts fields."""
    ref = reference_date or clock.today()
    result = parse_structured(
        _SYSTEM_PROMPT
        + f"\n\nReference date (resolve relative dates like \"today\"/\"last week\" against this): {ref.isoformat()}",
        description,
        StockTransactionEstimate,
        provider=provider,
        max_tokens=1024,
    )
    return result.parsed
