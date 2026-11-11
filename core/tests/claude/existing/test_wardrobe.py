from quintacle_core.nodes.wardrobe.llm import OutfitComponent, OutfitSuggestion, resolve_outfit
from quintacle_core.nodes.wardrobe.store import OutfitStore, WardrobeItemStore

KNOWN = [{"name": "Black Bomber Jacket", "category": "jacket", "description": "leather"}]


def test_item_store_round_trip(tmp_path):
    store = WardrobeItemStore(tmp_path)
    store.write("Black Bomber Jacket", "jacket", "leather, worn in fall")

    items = store.all()
    assert len(items) == 1
    assert items[0]["name"] == "Black Bomber Jacket"
    assert items[0]["category"] == "jacket"


def test_item_asset_save_and_read_round_trip(tmp_path):
    store = WardrobeItemStore(tmp_path)
    rel_path = store.save_asset("Jacket Photo.jpg", b"fake-jpeg-bytes")

    assert rel_path == "assets/jacket-photo.jpg"
    assert store.read_asset(rel_path) == b"fake-jpeg-bytes"


def test_item_write_with_asset_persists_in_frontmatter(tmp_path):
    store = WardrobeItemStore(tmp_path)
    asset_path = store.save_asset("jacket.jpg", b"data")
    store.write("Black Bomber Jacket", "jacket", "leather", assets=[asset_path])

    items = store.all()
    assert items[0]["assets"] == ["assets/jacket.jpg"]


def test_outfit_store_round_trip(tmp_path):
    store = OutfitStore(tmp_path)
    store.write("Fall Casual", ["Black Bomber Jacket", "Sunglasses"])

    outfits = store.all()
    assert outfits[0]["items"] == ["Black Bomber Jacket", "Sunglasses"]


def test_outfit_photo_saved_as_is_with_no_items(tmp_path):
    """A full-outfit mirror-selfie drop — no decomposition into matched
    wardrobe items, the photo itself is the record."""
    store = OutfitStore(tmp_path)
    asset_path = store.save_asset("mirror-selfie.jpg", b"fake-jpeg-bytes")
    store.write("Navy Casual Friday Fit", [], asset=asset_path)

    outfits = store.all()
    assert outfits[0]["items"] == []
    assert outfits[0]["asset"] == "assets/mirror-selfie.jpg"
    assert store.read_asset(asset_path) == b"fake-jpeg-bytes"


def test_matched_outfit_item_reuses_existing_not_flagged_new():
    suggestion = OutfitSuggestion(
        outfit_name="Fall Casual",
        items=[OutfitComponent(name="black bomber jacket", category="jacket")],
    )
    resolved = resolve_outfit(suggestion, KNOWN)

    assert resolved["items"][0]["name"] == "Black Bomber Jacket"
    assert resolved["items"][0]["is_new"] is False


def test_unmatched_outfit_item_flagged_new():
    suggestion = OutfitSuggestion(
        outfit_name="Fall Casual",
        items=[OutfitComponent(name="Sunglasses", category="accessory", description="aviators")],
    )
    resolved = resolve_outfit(suggestion, KNOWN)

    assert resolved["items"][0]["is_new"] is True
    assert resolved["items"][0]["description"] == "aviators"
