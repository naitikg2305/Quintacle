from quintacle_core.nodes.finance.store import CreditCardStore, InvestmentStore


def test_write_then_all(tmp_path):
    store = CreditCardStore(tmp_path)
    store.write(
        "Chase Sapphire Preferred",
        issuer="Chase",
        annual_fee=95,
        rewards_summary="3x dining, 2x travel, 1x everything else",
        points_balance=42000,
        signup_bonus="60,000 points after $4,000 spend in 3 months",
        notes="Great for transferring to airline partners.",
    )

    cards = store.all()
    assert len(cards) == 1
    assert cards[0]["name"] == "Chase Sapphire Preferred"
    assert cards[0]["issuer"] == "Chase"
    assert cards[0]["annual_fee"] == 95
    assert cards[0]["points_balance"] == 42000
    assert cards[0]["notes"] == "Great for transferring to airline partners."


def test_rewrite_at_same_name_updates_in_place(tmp_path):
    """'I can update them myself' — re-saving the same card overwrites it,
    doesn't fork a duplicate."""
    store = CreditCardStore(tmp_path)
    store.write("Amex Gold", points_balance=10000)
    store.write("Amex Gold", points_balance=15000)

    cards = store.all()
    assert len(cards) == 1
    assert cards[0]["points_balance"] == 15000


def test_get_returns_none_for_unknown_card(tmp_path):
    store = CreditCardStore(tmp_path)
    assert store.get("Nonexistent Card") is None


def test_structured_fields_are_readable_in_the_note_body(tmp_path):
    """Regression: the folder-scoped chat (kb/chat.py) only ever reads a
    note's BODY, never its frontmatter — verified live that putting
    rewards/points/fee ONLY in frontmatter made them invisible to "what's my
    best redemption strategy" chat. They must render into the body too."""
    from quintacle_core.nodes.kb.store import KBStore

    store = CreditCardStore(tmp_path)
    store.write(
        "Chase Sapphire Preferred",
        issuer="Chase",
        annual_fee=95,
        rewards_summary="3x dining, 2x travel",
        points_balance=42000,
        signup_bonus="60k after $4k spend",
    )

    kb_store = KBStore(tmp_path)
    body = kb_store.read("Organisation/Finance/Credit Cards", "chase-sapphire-preferred")
    assert body is not None
    assert "3x dining, 2x travel" in body
    assert "42000" in body
    assert "60k after $4k spend" in body
    assert "Chase" in body


def test_investment_write_then_all(tmp_path):
    store = InvestmentStore(tmp_path)
    store.write("Apple", symbol="AAPL", shares=10, cost_basis=150, account="Fidelity Roth IRA", purchase_date="2024-01-15")

    holdings = store.all()
    assert len(holdings) == 1
    assert holdings[0]["symbol"] == "AAPL"
    assert holdings[0]["shares"] == 10
    assert holdings[0]["cost_basis"] == 150
    assert holdings[0]["account"] == "Fidelity Roth IRA"


def test_investment_rewrite_at_same_name_updates_in_place(tmp_path):
    store = InvestmentStore(tmp_path)
    store.write("Apple", symbol="AAPL", shares=10, cost_basis=150)
    store.write("Apple", symbol="AAPL", shares=15, cost_basis=160)

    holdings = store.all()
    assert len(holdings) == 1
    assert holdings[0]["shares"] == 15
    assert holdings[0]["cost_basis"] == 160


def test_investment_structured_fields_readable_in_body(tmp_path):
    """Same chat-visibility requirement as credit cards — 'discuss stock
    strategy' needs the folder-scoped chat to actually see the holding."""
    from quintacle_core.nodes.kb.store import KBStore

    store = InvestmentStore(tmp_path)
    store.write("Apple", symbol="AAPL", shares=10, cost_basis=150, account="Fidelity Roth IRA")

    kb_store = KBStore(tmp_path)
    body = kb_store.read("Organisation/Finance/Stocks & Investments", "apple")
    assert body is not None
    assert "AAPL" in body
    assert "10" in body
    assert "150" in body
    assert "Fidelity Roth IRA" in body
    assert "1,500.00" in body  # total invested = shares * cost_basis, computed for you
