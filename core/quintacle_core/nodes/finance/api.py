from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..journal.normalize import canonicalize_name
from ...retrieval import safe_index_log_row
from . import insights, statements
from .accounts import ACCOUNT_TYPES, AccountStore, summarize
from .store import CreditCardStore, InvestmentStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/credit-cards", tags=["finance"])
_store: CreditCardStore | None = None

investments_router = APIRouter(prefix="/investments", tags=["finance"])
_investment_store: InvestmentStore | None = None
_account_store: AccountStore | None = None

# Spend insights + the statement-drop import lane (next-wave-plan §1/§2b).
# Lives here rather than logs/api.py because it's finance-page surface area;
# the data it reads/writes is still the logs repo's expense/income tables.
finance_router = APIRouter(prefix="/finance", tags=["finance"])


def _logs_repo():
    # Late import + late lookup: the repo is initialized by create_app() after
    # routers are imported, and logs.api importing this module back would be a
    # cycle if done at module level.
    from ..logs.api import get_repo

    return get_repo()


def init_store(kb_root) -> None:
    global _store, _investment_store, _account_store
    _store = CreditCardStore(kb_root)
    _investment_store = InvestmentStore(kb_root)
    _account_store = AccountStore(kb_root)


def get_account_store() -> AccountStore:
    if _account_store is None:
        raise RuntimeError("account store not initialized — call init_store() first")
    return _account_store


def get_store() -> CreditCardStore:
    if _store is None:
        raise RuntimeError("credit card store not initialized — call init_store() first")
    return _store


def get_investment_store() -> InvestmentStore:
    if _investment_store is None:
        raise RuntimeError("investment store not initialized — call init_store() first")
    return _investment_store


class CreditCardCreate(BaseModel):
    name: str
    issuer: str | None = None
    annual_fee: float | None = None
    rewards_summary: str | None = None
    points_balance: float | None = None
    signup_bonus: str | None = None
    notes: str | None = None


@router.post("")
def create_credit_card(body: CreditCardCreate) -> dict:
    """Upsert by name — re-saving the same card updates it in place, so
    "I can update them myself" (a new points balance, a changed benefit)
    never forks a duplicate card. A field left OUT of the request keeps its
    existing value instead of being blanked — e.g. "just bump my points
    balance" doesn't also wipe the rewards summary/notes/etc already saved."""
    store = get_store()
    known_names = [c["name"] for c in store.all()]
    resolved_name = canonicalize_name(body.name, known_names)
    existing = store.get(resolved_name) or {}
    provided = body.model_dump(exclude={"name"}, exclude_unset=True)
    merged = {
        "issuer": existing.get("issuer", ""),
        "annual_fee": existing.get("annual_fee"),
        "rewards_summary": existing.get("rewards_summary", ""),
        "points_balance": existing.get("points_balance"),
        "signup_bonus": existing.get("signup_bonus", ""),
        "notes": existing.get("notes", ""),
        **provided,
    }
    slug = store.write(
        resolved_name,
        merged["issuer"],
        merged["annual_fee"],
        merged["rewards_summary"],
        merged["points_balance"],
        merged["signup_bonus"],
        merged["notes"],
    )
    return {"name": resolved_name, "slug": slug}


@router.get("")
def list_credit_cards() -> list[dict]:
    return get_store().all()


class InvestmentCreate(BaseModel):
    name: str
    symbol: str | None = None
    shares: float | None = None
    cost_basis: float | None = None
    account: str | None = None
    purchase_date: str | None = None
    notes: str | None = None


@investments_router.post("")
def create_investment(body: InvestmentCreate) -> dict:
    """Same upsert-by-name, merge-on-partial-update contract as credit
    cards — updating just the share count doesn't blank the account/notes/
    everything else already saved."""
    store = get_investment_store()
    known_names = [i["name"] for i in store.all()]
    resolved_name = canonicalize_name(body.name, known_names)
    existing = store.get(resolved_name) or {}
    provided = body.model_dump(exclude={"name"}, exclude_unset=True)
    merged = {
        "symbol": existing.get("symbol", ""),
        "shares": existing.get("shares"),
        "cost_basis": existing.get("cost_basis"),
        "account": existing.get("account", ""),
        "purchase_date": existing.get("purchase_date"),
        "notes": existing.get("notes", ""),
        **provided,
    }
    slug = store.write(
        resolved_name,
        merged["symbol"],
        merged["shares"],
        merged["cost_basis"],
        merged["account"],
        merged["purchase_date"],
        merged["notes"],
    )
    return {"name": resolved_name, "slug": slug}


@investments_router.get("")
def list_investments() -> list[dict]:
    return get_investment_store().all()


# --- insights (deterministic analytics — SQL/arithmetic only, zero models) ---


@finance_router.get("/insights/monthly")
def insights_monthly(months: int = 12) -> list[dict]:
    """Per-month totals by kind, income, savings (rate), and month-over-month
    deltas — oldest first. Pure SQL + code; see nodes/finance/insights.py."""
    return insights.monthly_breakdown(_logs_repo().conn, months=max(1, min(months, 60)))


@finance_router.get("/insights/merchants")
def insights_merchants(start: date, end: date, limit: int = 25) -> list[dict]:
    return insights.merchant_rollup(_logs_repo().conn, start, end, limit=max(1, min(limit, 200)))


@finance_router.get("/insights/movers")
def insights_movers(limit: int = 10) -> list[dict]:
    """Biggest per-merchant swings, this month vs last."""
    return insights.merchant_movers(_logs_repo().conn, limit=max(1, min(limit, 50)))


@finance_router.get("/insights/subscriptions")
def insights_subscriptions() -> dict:
    """Recurring charges detected by cadence arithmetic (same merchant +
    similar amount at a weekly/monthly/yearly gap) — no model judgment."""
    return insights.detect_subscriptions(_logs_repo().conn)


# --- accounts: manually-recorded balances + net worth (2026-11-05) ---
# Write gating: these are the Save step of the in-app form (propose→review→
# Save); balance history is append-only, with an explicit per-snapshot delete
# as the undo. See nodes/finance/accounts.py for the net-worth rule.


class AccountUpsert(BaseModel):
    name: str
    account_type: str
    institution: str = ""
    notes: str = ""
    # Optional opening balance, appended as the first/next snapshot.
    balance: float | None = None
    as_of: date | None = None


class BalanceIn(BaseModel):
    balance: float
    as_of: date | None = None
    note: str = ""


def _stock_positions() -> dict | None:
    # Late import: the stocks node is initialized independently in create_app().
    try:
        from ..stocks.api import get_stocks_repo
        from ..stocks.positions import compute_positions

        repo = get_stocks_repo()
        return compute_positions([dict(r) for r in repo.transactions()], repo.latest_prices())
    except RuntimeError:
        return None


@finance_router.get("/accounts")
def list_accounts() -> dict:
    """Every account with its full snapshot history + latest balance, the
    bucket totals and net worth (incl. uncovered stock-ledger holdings) —
    all computed in code."""
    result = summarize(get_account_store().all(), _stock_positions())
    result["account_types"] = ACCOUNT_TYPES
    return result


@finance_router.post("/accounts")
def upsert_account(body: AccountUpsert) -> dict:
    """Upsert by name (slug). Descriptive fields only — the balance history
    is never rewritten; a supplied `balance` is APPENDED as a snapshot."""
    from ...clock import today

    store = get_account_store()
    try:
        slug = store.upsert(body.name, body.account_type, body.institution, body.notes)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if body.balance is not None:
        store.add_balance(slug, body.balance, body.as_of or today())
    return {"slug": slug}


@finance_router.post("/accounts/{slug}/balance")
def add_account_balance(slug: str, body: BalanceIn) -> dict:
    from ...clock import today

    try:
        acct = get_account_store().add_balance(slug, body.balance, body.as_of or today(), body.note)
    except KeyError:
        raise HTTPException(404, f"no account {slug!r}")
    return {"slug": acct["slug"], "snapshots": len(acct["balances"])}


@finance_router.delete("/accounts/{slug}/balance/{index}")
def delete_account_balance(slug: str, index: int) -> dict:
    try:
        acct = get_account_store().delete_balance(slug, index)
    except KeyError:
        raise HTTPException(404, f"no account {slug!r}")
    except IndexError:
        raise HTTPException(404, f"no snapshot #{index}")
    return {"slug": acct["slug"], "snapshots": len(acct["balances"])}


@finance_router.delete("/accounts/{slug}")
def delete_account(slug: str) -> dict:
    if not get_account_store().delete(slug):
        raise HTTPException(404, f"no account {slug!r}")
    return {"deleted": slug}


# --- statement import lane (§2b: statements come in as DROPS) ---


class StatementParseRequest(BaseModel):
    filename: str = ""
    text: str
    # CSV column mapping override from the review UI (header names + negate);
    # None means "guess from the headers/data". Ignored for OFX/QFX.
    mapping: dict | None = None


@finance_router.post("/statement/parse")
def statement_parse(body: StatementParseRequest) -> dict:
    """Deterministic CSV/OFX/QFX statement parse — NEVER writes. Returns the
    proposed transactions (with duplicate flags) + the column mapping used,
    so the review UI can correct the mapping and re-parse. The same function
    /drop's statement branch uses, so Drop and any direct caller agree."""
    return parse_statement_text(body.filename, body.text, body.mapping)


def parse_statement_text(filename: str, text: str, mapping: dict | None = None) -> dict:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext in ("ofx", "qfx") or (ext == "" and "<OFX" in text.upper()):
        result = statements.parse_ofx(text)
    elif ext == "csv" or ext == "":
        result = statements.parse_csv_statement(text, mapping)
    else:
        raise HTTPException(400, f"unsupported statement format: {ext!r} (csv/ofx/qfx here; PDFs go through Drop)")
    statements.annotate_duplicates(result["transactions"], _logs_repo())
    result["filename"] = filename
    return result


class StatementTxnIn(BaseModel):
    date: date
    amount: float
    merchant: str = ""
    category: str = ""
    notes: str = ""
    kind: str = "regular"
    # Set by the review UI when the user re-checks a row the dedup pass
    # flagged — the explicit "yes, write it anyway".
    allow_duplicate: bool = False


class StatementImportRequest(BaseModel):
    transactions: list[StatementTxnIn]
    statement_name: str = ""


@finance_router.post("/statement/import")
def statement_import(body: StatementImportRequest) -> dict:
    """The gated write behind the statement review: every row the user kept
    becomes one expense_log row (markdown + SQLite, same path as any logged
    expense). Dedup is re-checked at write time — an already-present
    date+amount+merchant is skipped, never double-written, unless the row
    carries the explicit allow_duplicate override. All written rows are
    event-grouped per statement (one `part_of` event, §2b)."""
    repo = _logs_repo()
    written_ids: list[int] = []
    skipped = 0
    for txn in body.transactions:
        if not txn.allow_duplicate and repo.expense_exists(txn.date, txn.amount, txn.merchant):
            skipped += 1
            continue
        note = txn.notes
        if body.statement_name:
            suffix = f"[statement: {body.statement_name}]"
            note = f"{note} {suffix}".strip() if note else suffix
        expense_id = repo.log_expense(txn.date, txn.amount, txn.merchant, txn.category, note, txn.kind)
        written_ids.append(expense_id)
        safe_index_log_row(f"expense:{expense_id}")  # retrieval index — failure-isolated

    event_id = None
    if len(written_ids) >= 2:
        # Same-event provenance, by construction (one statement = one batch).
        # Additive and never blocking — the expenses above are already saved.
        try:
            from ...graph_capture import link_event

            event_id = link_event([f"expense:{i}" for i in written_ids], None)["event_id"]
        except Exception:
            logger.warning("statement import: event linking failed", exc_info=True)
    return {"written": len(written_ids), "skipped_duplicates": skipped, "ids": written_ids, "event_id": event_id}
