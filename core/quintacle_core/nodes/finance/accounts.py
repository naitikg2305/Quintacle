"""Manually-recorded account balances (2026-11-05, unified Finances page):
checking / savings / cash / brokerage / 401k / IRA / HSA / crypto, plus
liabilities (credit-card balance owed, loans).

Shape:
- One markdown file per account under Organisation/Finance/Accounts/ —
  markdown is the source of truth, no SQLite mirror (nothing holds a foreign
  key into an account; same reasoning as CreditCardStore). A different store
  from CreditCardStore on purpose: that one records card *benefits/points*;
  a `credit_card` account here records the *balance owed*.
- Balances are an append-only list of dated snapshots in frontmatter
  (`balances: [{date, balance, note}]`). "Updating a balance" appends; history
  is never overwritten, so balance-over-time is always reconstructible. A
  mistaken snapshot can be removed explicitly (DELETE by index) — the
  in-app form is the review step, the delete is the undo.
- Liabilities are entered as the POSITIVE amount owed; the summary subtracts
  them. Every total (buckets, net worth, history) is computed here in code,
  never on the page.

Net-worth rule vs the stocks ledger (no double counting): a stock position
from nodes/stocks counts toward net worth UNLESS every account name on its
transactions matches (case-insensitive) a recorded brokerage/retirement
account here — then that account's recorded balance already covers it.
Positions with no account name always count. Uncovered positions count at
market value when a price snapshot exists, otherwise at cost basis.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import frontmatter

from ...markdown_paths import resolve_nested, safe_metadata, slugify

ACCOUNTS_HOME = "Organisation/Finance/Accounts"

# type -> bucket. Buckets drive the net-worth breakdown.
ACCOUNT_TYPES: dict[str, str] = {
    "checking": "liquid",
    "savings": "liquid",
    "cash": "liquid",
    "brokerage": "investments",
    "crypto": "investments",
    "401k": "retirement",
    "ira": "retirement",
    "roth_ira": "retirement",
    "hsa": "retirement",
    "other_asset": "other",
    "credit_card": "liabilities",
    "loan": "liabilities",
}
BUCKETS = ("liquid", "investments", "retirement", "other", "liabilities")
# Account types whose recorded balance can "cover" stock-ledger positions.
_COVERING_TYPES = {t for t, b in ACCOUNT_TYPES.items() if b in ("investments", "retirement")}


def _body(name: str, account_type: str, institution: str, balances: list[dict], notes: str) -> str:
    """Chat-readable summary (folder-scoped chat reads bodies only — same
    reason as finance/store.py's _compose_body)."""
    lines = [f"# {name}", f"- Type: {account_type}"]
    if institution:
        lines.append(f"- Institution: {institution}")
    if balances:
        latest = balances[-1]
        owed = " owed" if ACCOUNT_TYPES.get(account_type) == "liabilities" else ""
        lines.append(f"- Latest balance: ${latest['balance']:,.2f}{owed} as of {latest['date']}")
        lines.append(f"- Snapshots recorded: {len(balances)}")
    body = "\n".join(lines)
    return f"{body}\n\n{notes}" if notes else body


def _sorted_balances(raw) -> list[dict]:
    out = []
    for i, b in enumerate(raw or []):
        try:
            out.append({"date": str(b["date"]), "balance": float(b["balance"]), "note": str(b.get("note") or ""), "_i": i})
        except (KeyError, TypeError, ValueError):
            continue  # a hand-edited malformed row degrades to "skipped", not a 500
    # Stable: same-day snapshots keep entry order, the later one wins as "latest".
    out.sort(key=lambda b: (b["date"], b["_i"]))
    for b in out:
        b.pop("_i")
    return out


class AccountStore:
    def __init__(self, kb_root: Path):
        self.kb_root = Path(kb_root)

    def _dir(self) -> Path:
        path = resolve_nested(self.kb_root, ACCOUNTS_HOME)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _path(self, slug: str) -> Path:
        return self._dir() / f"{slugify(slug)}.md"

    def _save(self, slug: str, meta: dict) -> None:
        post = frontmatter.Post(_body(meta["name"], meta["account_type"], meta["institution"], meta["balances"], meta["notes"]))
        for key in ("name", "account_type", "institution", "notes", "balances"):
            post[key] = meta[key]
        post["type"] = "finance_account"
        self._path(slug).write_text(frontmatter.dumps(post), encoding="utf-8")

    def get(self, slug: str) -> dict | None:
        path = self._path(slug)
        if not path.exists():
            return None
        post = frontmatter.loads(path.read_text(encoding="utf-8"))
        meta = safe_metadata(post, path.stem, {"account_type": "other_asset", "institution": "", "notes": ""})
        if meta.get("account_type") not in ACCOUNT_TYPES:
            meta["account_type"] = "other_asset"
        meta["balances"] = _sorted_balances(meta.get("balances"))
        meta.pop("type", None)
        return {**meta, "slug": path.stem}

    def all(self) -> list[dict]:
        out = []
        for p in sorted(self._dir().glob("*.md")):
            acct = self.get(p.stem)
            if acct is not None:
                out.append(acct)
        return out

    def upsert(self, name: str, account_type: str, institution: str = "", notes: str = "") -> str:
        """Create or edit an account's descriptive fields. Never touches the
        balance history."""
        if account_type not in ACCOUNT_TYPES:
            raise ValueError(f"account_type must be one of {tuple(ACCOUNT_TYPES)}")
        if not name.strip():
            raise ValueError("name is required")
        slug = slugify(name)
        existing = self.get(slug)
        meta = {
            "name": name.strip(),
            "account_type": account_type,
            "institution": institution,
            "notes": notes,
            "balances": existing["balances"] if existing else [],
        }
        self._save(slug, meta)
        return slug

    def add_balance(self, slug: str, balance: float, as_of: date, note: str = "") -> dict:
        acct = self.get(slug)
        if acct is None:
            raise KeyError(slug)
        acct["balances"].append({"date": as_of.isoformat(), "balance": round(float(balance), 2), "note": note})
        acct["balances"] = _sorted_balances(acct["balances"])
        self._save(acct["slug"], acct)
        return acct

    def delete_balance(self, slug: str, index: int) -> dict:
        """Removes ONE snapshot by its position in the date-sorted list (what
        GET returns) — the explicit undo for a mistyped entry."""
        acct = self.get(slug)
        if acct is None:
            raise KeyError(slug)
        if not 0 <= index < len(acct["balances"]):
            raise IndexError(index)
        acct["balances"].pop(index)
        self._save(acct["slug"], acct)
        return acct

    def delete(self, slug: str) -> bool:
        path = self._path(slug)
        if path.exists():
            path.unlink()
            return True
        return False


def _signed(account: dict, balance: float) -> float:
    return -balance if ACCOUNT_TYPES[account["account_type"]] == "liabilities" else balance


def summarize(accounts: list[dict], stock_positions: dict | None = None) -> dict:
    """Pure arithmetic: per-account latest balance, bucket totals, net worth,
    and a net-worth-over-time series from the recorded snapshots.

    `stock_positions` is compute_positions()'s output (or None). See the
    module docstring for the no-double-counting rule."""
    buckets = {b: 0.0 for b in BUCKETS}
    rows = []
    for a in accounts:
        latest = a["balances"][-1] if a["balances"] else None
        bucket = ACCOUNT_TYPES[a["account_type"]]
        if latest:
            buckets[bucket] += latest["balance"]
        rows.append(
            {
                **a,
                "bucket": bucket,
                "latest_balance": latest["balance"] if latest else None,
                "latest_date": latest["date"] if latest else None,
            }
        )

    covering = {a["name"].strip().lower() for a in accounts if a["account_type"] in _COVERING_TYPES and a["balances"]}
    holdings_value = 0.0
    holdings_at_cost = False
    covered_symbols: list[str] = []
    counted_symbols: list[str] = []
    for p in (stock_positions or {}).get("positions", []):
        if p["qty"] <= 1e-9:
            continue
        accts = [x.strip().lower() for x in p.get("accounts") or [] if x.strip()]
        if accts and all(x in covering for x in accts):
            covered_symbols.append(p["symbol"])
            continue
        counted_symbols.append(p["symbol"])
        if p.get("market_value") is not None:
            holdings_value += p["market_value"]
        else:
            holdings_value += p["cost_basis"]
            holdings_at_cost = True

    assets = buckets["liquid"] + buckets["investments"] + buckets["retirement"] + buckets["other"] + holdings_value
    net_worth = assets - buckets["liabilities"]

    # Net worth over time, from recorded snapshots only (the stock ledger has
    # no price history worth trusting per-date here): at each snapshot date,
    # each account contributes its latest balance as of that date.
    dates = sorted({b["date"] for a in accounts for b in a["balances"]})
    history = []
    for d in dates:
        total = 0.0
        for a in accounts:
            upto = [b for b in a["balances"] if b["date"] <= d]
            if upto:
                total += _signed(a, upto[-1]["balance"])
        history.append({"date": d, "net_worth": round(total, 2)})

    return {
        "accounts": rows,
        "buckets": {k: round(v, 2) for k, v in buckets.items()},
        "stock_holdings_counted": round(holdings_value, 2),
        "stock_holdings_at_cost": holdings_at_cost,
        "stock_symbols_counted": counted_symbols,
        "stock_symbols_covered": covered_symbols,
        # Brokerage/crypto balances + uncovered ledger holdings (retirement separate).
        "investments_total": round(buckets["investments"] + holdings_value, 2),
        "assets": round(assets, 2),
        "liabilities": round(buckets["liabilities"], 2),
        "net_worth": round(net_worth, 2),
        "as_of": dates[-1] if dates else None,
        "history": history,
    }
