"""2026-11-11: an item's typed name wins when the model's name only drops
words from it (the live suite caught qwen naming 'CeraVe hydrating
cleanser' as just 'Hydrating Cleanser')."""
from quintacle_core.nodes.journal.normalize import keep_typed_name


def test_brand_dropped_by_model_is_restored():
    assert keep_typed_name("Hydrating Cleanser", "CeraVe hydrating cleanser, use AM and PM") == "CeraVe hydrating cleanser"


def test_model_name_kept_when_it_adds_or_differs():
    assert keep_typed_name("Dyson V15 Vacuum", "Dyson V15 vacuum, bought 2025") == "Dyson V15 Vacuum"
    assert keep_typed_name("Running shoes", "Nike pegasus 40, size 10") == "Running shoes"


def test_long_rambling_text_is_not_used_as_a_name():
    text = "so i finally got this really nice cleanser from the store near my place today"
    assert keep_typed_name("Cleanser", text) == "Cleanser"
