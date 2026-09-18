from quintacle_core.nodes.home.store import HomeItemStore, ResidenceStore


def test_residence_write_then_find(tmp_path):
    store = ResidenceStore(tmp_path)
    folder, slug = store.write("Standard", "College Park", address="123 Main St", moved_in="2022-08-01")

    residence = store.find("Standard")
    assert residence["name"] == "Standard"
    assert residence["city"] == "College Park"
    assert residence["address"] == "123 Main St"
    assert residence["folder"] == folder
    assert slug == "standard"


def test_residence_all_spans_multiple_cities(tmp_path):
    store = ResidenceStore(tmp_path)
    store.write("Standard", "College Park", moved_in="2022-08-01", moved_out="2024-06-01")
    store.write("Iris 307", "DC", moved_in="2024-06-01")

    residences = store.all()
    assert {r["name"] for r in residences} == {"Standard", "Iris 307"}


def test_residence_missing_returns_none(tmp_path):
    store = ResidenceStore(tmp_path)
    assert store.find("Nope") is None


def test_home_items_nested_under_residence_folder(tmp_path):
    residence_store = ResidenceStore(tmp_path)
    folder, _ = residence_store.write("Standard", "College Park")

    item_store = HomeItemStore(tmp_path)
    item_store.write(folder, "Couch", category="furniture", location="living room", purchase_price=800.0)

    items = item_store.all(folder)
    assert len(items) == 1
    assert items[0]["name"] == "Couch"
    assert items[0]["location"] == "living room"
    assert items[0]["purchase_price"] == 800.0


def test_home_items_scoped_per_residence_not_shared(tmp_path):
    residence_store = ResidenceStore(tmp_path)
    folder_a, _ = residence_store.write("Standard", "College Park")
    folder_b, _ = residence_store.write("Iris 307", "DC")

    item_store = HomeItemStore(tmp_path)
    item_store.write(folder_a, "Couch")
    item_store.write(folder_b, "Desk")

    assert [i["name"] for i in item_store.all(folder_a)] == ["Couch"]
    assert [i["name"] for i in item_store.all(folder_b)] == ["Desk"]


def test_home_item_asset_save_and_read_round_trip(tmp_path):
    residence_store = ResidenceStore(tmp_path)
    folder, _ = residence_store.write("Standard", "College Park")

    item_store = HomeItemStore(tmp_path)
    rel_path = item_store.save_asset(folder, "Couch Photo.jpg", b"fake-jpeg-bytes")

    assert rel_path == "assets/couch-photo.jpg"
    assert item_store.read_asset(folder, rel_path) == b"fake-jpeg-bytes"


def test_no_purchase_price_stored_as_none(tmp_path):
    residence_store = ResidenceStore(tmp_path)
    folder, _ = residence_store.write("Standard", "College Park")

    item_store = HomeItemStore(tmp_path)
    item_store.write(folder, "Halloween Decor", category="decor", location="closet, box 3")

    items = item_store.all(folder)
    assert items[0]["purchase_price"] is None
