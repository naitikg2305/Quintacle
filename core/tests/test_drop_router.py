from quintacle_core.nodes.drop_router import parse_prefix


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
