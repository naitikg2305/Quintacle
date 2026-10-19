from __future__ import annotations

import base64
from typing import Literal

from pydantic import BaseModel

from ...llm_config import DEFAULT_MODEL
from ...llm_dispatch import parse_structured


class CreditCardEstimate(BaseModel):
    suggested_name: str
    issuer: str = ""
    annual_fee: float | None = None
    rewards_summary: str = ""
    points_balance: float | None = None
    signup_bonus: str = ""
    notes: str = ""


_SYSTEM_PROMPT = (
    "Structure this into a credit card entry: suggested_name (the card's name, e.g. \"Chase "
    "Sapphire Preferred\"), issuer (the bank), annual_fee (a number in dollars if stated, else "
    "null), rewards_summary (a short description of reward categories/multipliers, e.g. \"3x "
    "dining, 2x travel, 1x everything else\"), points_balance (a number if a current balance is "
    "stated, else null), signup_bonus (a short description if mentioned), and notes (anything "
    "else worth remembering — redemption tips, why you got it, perks)."
)


def structure_credit_card(description: str, provider: str | None = None) -> CreditCardEstimate:
    """For the explicit "creditcard:"/"card:" prefix — intent already
    stated, so no relevance gate, always extracts fields."""
    return parse_structured(_SYSTEM_PROMPT, description, CreditCardEstimate, provider=provider, max_tokens=1024).parsed


class InvestmentEstimate(BaseModel):
    suggested_name: str
    symbol: str = ""
    shares: float | None = None
    cost_basis: float | None = None
    account: str = ""
    purchase_date: str | None = None
    notes: str = ""


_INVESTMENT_SYSTEM_PROMPT = (
    "Structure this into an investment holding entry: suggested_name (the company/fund name, "
    "e.g. \"Apple\" or \"VOO\"), symbol (the ticker if stated/known, e.g. \"AAPL\"), shares (a "
    "number if stated, else null), cost_basis (the average price PER SHARE paid, in dollars, if "
    "stated — if only a total dollar amount and share count are given, compute the per-share "
    "average yourself), account (the brokerage/account it's held in, if stated), purchase_date "
    "(YYYY-MM-DD if stated), and notes (why you bought it, a strategy note, anything else worth "
    "remembering — this is a manually-tracked record, not a live price feed, so don't invent a "
    "current price)."
)


def structure_investment(description: str, provider: str | None = None) -> InvestmentEstimate:
    """For the explicit "invest:"/"stock:" prefix — intent already stated,
    so no relevance gate, always extracts fields."""
    return parse_structured(_INVESTMENT_SYSTEM_PROMPT, description, InvestmentEstimate, provider=provider, max_tokens=1024).parsed


class _StatementTxn(BaseModel):
    date: str  # YYYY-MM-DD as printed on the statement
    amount: float  # positive dollars spent
    merchant: str = ""
    notes: str = ""
    kind: Literal["subscription", "food", "alcohol", "experience", "shopping", "big_purchase", "regular"] = "regular"


class _StatementExtraction(BaseModel):
    transactions: list[_StatementTxn]


_STATEMENT_SYSTEM = (
    "This is a bank or credit card statement. Extract EVERY purchase/charge transaction as a row: "
    "date (YYYY-MM-DD exactly as printed), amount (the positive dollar amount charged), merchant "
    "(the payee/description as printed, lightly cleaned), notes (any extra detail on the line, else "
    "empty), and kind — exactly one of: subscription (a recurring bill/membership charge), food (a "
    "meal or non-alcoholic food/drink purchase), alcohol (a drink/bar tab/bottle purchase), "
    "experience (paying to do something — an activity, ticket, entrance fee), shopping (clothing, "
    "gear, everyday retail), big_purchase (a large one-off purchase), or regular (anything else). "
    "SKIP payments, credits, refunds, interest, and fees-reversals — only money spent. Do not "
    "compute or invent anything: only transcribe what the statement shows."
)


def extract_statement_transactions(data: bytes, media_type: str, user_description: str = "") -> list[dict]:
    """PDF/photo statements through the SAME cloud vision lane receipts use
    (drop_router.extract_finance_from_receipt's pattern — vision+schema sites
    deliberately stay cloud, per the 2026-10-15 local-first amendment). The
    model only TRANSCRIBES rows; every number it returns is reviewed in the
    statement gate and all downstream arithmetic happens in code. anthropic
    imports lazily so the deterministic CSV/OFX lane never touches it."""
    import anthropic

    if media_type == "application/pdf":
        source_block = {
            "type": "document",
            "source": {"type": "base64", "media_type": media_type, "data": base64.standard_b64encode(data).decode()},
        }
    else:
        source_block = {
            "type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": base64.standard_b64encode(data).decode()},
        }
    content: list[dict] = [source_block]
    if user_description.strip():
        content.append({"type": "text", "text": user_description.strip()})
    client = anthropic.Anthropic()
    response = client.messages.parse(
        model=DEFAULT_MODEL,
        max_tokens=8192,
        system=_STATEMENT_SYSTEM,
        messages=[{"role": "user", "content": content}],
        output_format=_StatementExtraction,
    )
    return [t.model_dump() for t in response.parsed_output.transactions]
