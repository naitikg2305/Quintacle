"""Free EOD price fetch — docs/next-wave-plan.md §2's decided exception to
local-first: market prices are PUBLIC data, so auto-fetch is privacy-clean,
but it stays pull-only (an explicit refresh endpoint; no background daemon)
and end-of-day only.

Default source is Stooq's plain-HTTP CSV quote endpoint: zero dependencies
beyond the stdlib, which keeps core/requirements.txt phone/Termux-safe.
yfinance (which drags in pandas) is strictly an optional lane — lazy import,
installed separately via core/stocks-requirements.txt, selected with
QUINTACLE_PRICE_SOURCE=yfinance or a per-request `source` param. Any fetch
failure degrades gracefully upstream: the refresh endpoint reports the error
per symbol and valuation keeps using the last stored snapshot, shown with
its (stale) date.
"""
from __future__ import annotations

import csv
import io
import os
import urllib.request

from ... import clock

DEFAULT_SOURCE = "stooq"


class PriceFetchError(Exception):
    """One symbol's fetch failing (network down, unknown ticker, source
    hiccup) — callers catch this per symbol; it must never take down a whole
    refresh."""


def _http_get(url: str, timeout: float = 10) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "quintacle/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as res:  # noqa: S310 — fixed https host below
        return res.read().decode("utf-8", errors="replace")


def _stooq_symbol(symbol: str) -> str:
    """Stooq namespaces US tickers as `aapl.us`; a symbol that already
    carries a market suffix (brk-b.us, ^spx) passes through untouched."""
    s = symbol.strip().lower()
    return s if ("." in s or s.startswith("^")) else f"{s}.us"


def fetch_stooq(symbol: str, http_get=None) -> dict:
    """Latest EOD quote from Stooq's CSV endpoint (no key, no dependency).
    `http_get` is injectable so tests run fully offline. Returns
    {"symbol", "price", "price_date", "source"} or raises PriceFetchError."""
    http_get = http_get or _http_get
    url = f"https://stooq.com/q/l/?s={_stooq_symbol(symbol)}&f=sd2t2ohlcv&h&e=csv"
    try:
        body = http_get(url)
    except Exception as e:  # noqa: BLE001 — any transport failure is the same degradation
        raise PriceFetchError(f"stooq fetch failed for {symbol}: {e}") from e

    rows = list(csv.DictReader(io.StringIO(body)))
    if not rows:
        raise PriceFetchError(f"stooq returned no data for {symbol}")
    row = rows[0]
    close, price_date = row.get("Close"), row.get("Date")
    if not close or close == "N/D" or not price_date or price_date == "N/D":
        raise PriceFetchError(f"stooq has no quote for {symbol} (unknown ticker?)")
    try:
        price = float(close)
    except ValueError as e:
        raise PriceFetchError(f"stooq returned an unparseable close for {symbol}: {close!r}") from e
    return {"symbol": symbol.strip().upper(), "price": price, "price_date": price_date, "source": "stooq"}


def fetch_yfinance(symbol: str) -> dict:
    """Optional yfinance lane — heavy deps (pandas), so it's lazy-imported
    and lives in core/stocks-requirements.txt, never core/requirements.txt.
    Same return/raise contract as fetch_stooq."""
    try:
        import yfinance  # noqa: PLC0415 — deliberate lazy import of an optional dep
    except ImportError as e:
        raise PriceFetchError(
            "yfinance is not installed — pip install -r core/stocks-requirements.txt, "
            "or use the default stooq source"
        ) from e
    try:
        history = yfinance.Ticker(symbol).history(period="5d", interval="1d")
    except Exception as e:  # noqa: BLE001
        raise PriceFetchError(f"yfinance fetch failed for {symbol}: {e}") from e
    if history is None or len(history) == 0:
        raise PriceFetchError(f"yfinance has no quote for {symbol}")
    last = history.iloc[-1]
    return {
        "symbol": symbol.strip().upper(),
        "price": float(last["Close"]),
        "price_date": history.index[-1].date().isoformat(),
        "source": "yfinance",
    }


def fetch_eod(symbol: str, source: str | None = None, http_get=None) -> dict:
    """One symbol's latest EOD snapshot from the chosen source (param >
    QUINTACLE_PRICE_SOURCE env > stooq default), plus `fetched_at` stamped in
    Eastern Time per clock.py."""
    source = source or os.environ.get("QUINTACLE_PRICE_SOURCE") or DEFAULT_SOURCE
    if source == "stooq":
        snapshot = fetch_stooq(symbol, http_get=http_get)
    elif source == "yfinance":
        snapshot = fetch_yfinance(symbol)
    else:
        raise PriceFetchError(f"unknown price source {source!r} (expected 'stooq' or 'yfinance')")
    return {**snapshot, "fetched_at": clock.now().isoformat()}
