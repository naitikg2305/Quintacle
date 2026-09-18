from quintacle_core.nodes.logs.meal_composer import ComposedComponent, MealCompositionSuggestion, resolve_composition

KNOWN = [
    {"id": 1, "name": "Greek Yogurt", "basis_amount_g": 170, "protein_g": 17, "carbs_g": 6, "fat_g": 0.7, "fiber_g": 0, "kcal": 100},
]


def test_matched_component_uses_real_ingredient_macros_not_ai_guess():
    suggestion = MealCompositionSuggestion(
        meal_name="Bowl",
        components=[
            ComposedComponent(
                name="greek yoghurt",  # deliberately different spelling/case
                quantity_g=170,
                protein_g=999,  # AI's guess — should be discarded since this matches
                carbs_g=999,
                fat_g=999,
                fiber_g=999,
                kcal=999,
                micros=[],
            )
        ],
    )
    resolved = resolve_composition(suggestion, KNOWN)

    comp = resolved["components"][0]
    assert comp["ingredient_id"] == 1
    assert comp["is_new"] is False
    assert comp["protein_g"] == 17
    assert comp["kcal"] == 100
    assert resolved["totals"]["kcal"] == 100


def test_matched_component_scales_by_quantity_over_ingredient_basis():
    suggestion = MealCompositionSuggestion(
        meal_name="Bowl",
        components=[
            ComposedComponent(name="Greek Yogurt", quantity_g=340, protein_g=0, carbs_g=0, fat_g=0, fiber_g=0, kcal=0, micros=[])
        ],
    )
    resolved = resolve_composition(suggestion, KNOWN)

    comp = resolved["components"][0]
    assert comp["protein_g"] == 34  # 2x the 170g basis
    assert comp["kcal"] == 200


def test_unmatched_component_flagged_new_and_keeps_ai_estimate():
    suggestion = MealCompositionSuggestion(
        meal_name="Bowl",
        components=[
            ComposedComponent(name="Banana", quantity_g=118, protein_g=1.3, carbs_g=27, fat_g=0.3, fiber_g=3.1, kcal=105, micros=[])
        ],
    )
    resolved = resolve_composition(suggestion, KNOWN)

    comp = resolved["components"][0]
    assert comp["ingredient_id"] is None
    assert comp["is_new"] is True
    assert comp["kcal"] == 105
    assert comp["basis_amount_g"] == 118
