from __future__ import annotations

import anthropic
from pydantic import BaseModel

from ...llm_config import DEFAULT_MODEL


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


def structure_credit_card(description: str) -> CreditCardEstimate:
    """For the explicit "creditcard:"/"card:" prefix — intent already
    stated, so no relevance gate, always extracts fields."""
    client = anthropic.Anthropic()
    response = client.messages.parse(
        model=DEFAULT_MODEL,
        max_tokens=1024,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": description}],
        output_format=CreditCardEstimate,
    )
    return response.parsed_output


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


def structure_investment(description: str) -> InvestmentEstimate:
    """For the explicit "invest:"/"stock:" prefix — intent already stated,
    so no relevance gate, always extracts fields."""
    client = anthropic.Anthropic()
    response = client.messages.parse(
        model=DEFAULT_MODEL,
        max_tokens=1024,
        system=_INVESTMENT_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": description}],
        output_format=InvestmentEstimate,
    )
    return response.parsed_output
