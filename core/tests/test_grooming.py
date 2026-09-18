from quintacle_core.nodes.grooming.llm import GroomingRoutineComponent, GroomingRoutineSuggestion, resolve_grooming_routine
from quintacle_core.nodes.grooming.store import GroomingItemStore, GroomingRoutineStore

KNOWN = [{"name": "CeraVe Foaming Cleanser", "category": "skincare", "description": "gel cleanser"}]


def test_item_store_round_trip(tmp_path):
    store = GroomingItemStore(tmp_path)
    store.write("CeraVe Foaming Cleanser", "skincare", "gel cleanser")

    items = store.all()
    assert len(items) == 1
    assert items[0]["name"] == "CeraVe Foaming Cleanser"
    assert items[0]["category"] == "skincare"


def test_item_asset_save_and_read_round_trip(tmp_path):
    store = GroomingItemStore(tmp_path)
    rel_path = store.save_asset("Product Photo.jpg", b"fake-jpeg-bytes")

    assert rel_path == "assets/product-photo.jpg"
    assert store.read_asset(rel_path) == b"fake-jpeg-bytes"


def test_item_write_with_asset_persists_in_frontmatter(tmp_path):
    store = GroomingItemStore(tmp_path)
    asset_path = store.save_asset("cleanser.jpg", b"data")
    store.write("CeraVe Foaming Cleanser", "skincare", "gel cleanser", asset=asset_path)

    items = store.all()
    assert items[0]["asset"] == "assets/cleanser.jpg"


def test_routine_store_round_trip(tmp_path):
    store = GroomingRoutineStore(tmp_path)
    store.write("AM Routine", ["CeraVe Foaming Cleanser", "Sunscreen"])

    routines = store.all()
    assert routines[0]["steps"] == ["CeraVe Foaming Cleanser", "Sunscreen"]


def test_matched_step_reuses_existing_not_flagged_new():
    suggestion = GroomingRoutineSuggestion(
        routine_name="AM Routine",
        steps=[GroomingRoutineComponent(name="cerave foaming cleanser", category="skincare")],
    )
    resolved = resolve_grooming_routine(suggestion, KNOWN)

    assert resolved["steps"][0]["name"] == "CeraVe Foaming Cleanser"
    assert resolved["steps"][0]["is_new"] is False


def test_unmatched_step_flagged_new():
    suggestion = GroomingRoutineSuggestion(
        routine_name="AM Routine",
        steps=[GroomingRoutineComponent(name="Sunscreen SPF 50", category="skincare", description="daily UV protection")],
    )
    resolved = resolve_grooming_routine(suggestion, KNOWN)

    assert resolved["steps"][0]["is_new"] is True
    assert resolved["steps"][0]["description"] == "daily UV protection"
