from quintacle_core.nodes.drop_router import looks_like_stock_transaction, parse_prefix


def test_recognized_prefix_splits_type_and_rest():
    assert parse_prefix("food: had a burrito") == ("food", "had a burrito")
    assert parse_prefix("todo: dentist friday") == ("todo", "dentist friday")


def test_prefix_aliases_map_to_canonical_type():
    assert parse_prefix("meal: lamb bowl") == ("food", "lamb bowl")
    assert parse_prefix("workout: 5x5 squat") == ("exercise", "5x5 squat")
    assert parse_prefix("expense: 12 dollars at chipotle") == ("finance", "12 dollars at chipotle")
    assert parse_prefix("label: nutrition facts photo") == ("ingredient_preset", "nutrition facts photo")


def test_unrecognized_keyword_returns_none():
    assert parse_prefix("random: whatever") is None


def test_no_colon_returns_none():
    assert parse_prefix("just a plain sentence with no prefix") is None


def test_prefix_with_no_content_after_colon_returns_none():
    assert parse_prefix("food:") is None
    assert parse_prefix("food:   ") is None


def test_case_insensitive_keyword():
    assert parse_prefix("FOOD: had a burrito") == ("food", "had a burrito")
    assert parse_prefix("Todo: dentist") == ("todo", "dentist")


# --- §8: stock-ledger + habit prefixes ---


def test_stock_and_invest_prefixes_route_to_the_ledger_lane():
    # The old static investment_entry mapping retired — both aliases now
    # propose a real stock_transaction (review → POST /stocks/transactions).
    assert parse_prefix("stock: bought 10 shares of AAPL at 150") == ("stock_transaction", "bought 10 shares of AAPL at 150")
    assert parse_prefix("invest: sold 5 VOO at $420") == ("stock_transaction", "sold 5 VOO at $420")


def test_habit_goal_budget_prefixes_route_to_habit_entry():
    assert parse_prefix("habit: gym 4x a week") == ("habit_entry", "gym 4x a week")
    assert parse_prefix("goal: 10 hrs of productivity a week") == ("habit_entry", "10 hrs of productivity a week")
    assert parse_prefix("budget: $200/month on eating out") == ("habit_entry", "$200/month on eating out")


# --- §8: the conservative unprefixed stock gate ---


def test_stock_gate_matches_share_and_stock_wording():
    assert looks_like_stock_transaction("bought 10 shares of AAPL at 150")
    assert looks_like_stock_transaction("sold 5 shares of VOO yesterday")
    assert looks_like_stock_transaction("purchased some Apple stock this morning")


def test_stock_gate_matches_ticker_at_price():
    assert looks_like_stock_transaction("bought AAPL at $150")
    assert looks_like_stock_transaction("sold 3 TSLA @ 420 in fidelity")


def test_stock_gate_rejects_ordinary_purchases():
    # A trade verb alone is not enough — no share/stock word, no ticker@price.
    assert not looks_like_stock_transaction("bought 10 apples at the store")
    assert not looks_like_stock_transaction("bought a coffee at $5 corner cafe")


def test_stock_gate_rejects_stocked_up_wording():
    # \bstock\b must not match "stocked", and there's no trade verb anyway.
    assert not looks_like_stock_transaction("stocked up on rice")


def test_stock_gate_requires_a_trade_verb():
    # Stock-shaped nouns without a buy/sell verb stay out of the lane —
    # "thinking about shares" is journal prose, not a transaction.
    assert not looks_like_stock_transaction("my AAPL shares are up a lot")
    assert not looks_like_stock_transaction("lowercase aapl at $150 is prose, not a ticker")
