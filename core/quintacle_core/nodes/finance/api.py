from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from ..journal.normalize import canonicalize_name
from .store import CreditCardStore, InvestmentStore

router = APIRouter(prefix="/credit-cards", tags=["finance"])
_store: CreditCardStore | None = None

investments_router = APIRouter(prefix="/investments", tags=["finance"])
_investment_store: InvestmentStore | None = None


def init_store(kb_root) -> None:
    global _store, _investment_store
    _store = CreditCardStore(kb_root)
    _investment_store = InvestmentStore(kb_root)


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
