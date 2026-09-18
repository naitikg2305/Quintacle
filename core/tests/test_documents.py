from quintacle_core.nodes.documents.store import DocumentStore


def test_write_then_read_round_trip(tmp_path):
    store = DocumentStore(tmp_path)
    store.write(
        "Passport",
        doc_type="passport",
        issued_date="2020-01-15",
        expiry_date="2030-01-15",
        status="active",
        notes="US passport",
    )

    doc = store.get("Passport")
    assert doc["name"] == "Passport"
    assert doc["doc_type"] == "passport"
    assert doc["issued_date"] == "2020-01-15"
    assert doc["expiry_date"] == "2030-01-15"
    assert doc["status"] == "active"
    assert doc["notes"] == "US passport"


def test_all_lists_every_document(tmp_path):
    store = DocumentStore(tmp_path)
    store.write("Passport", doc_type="passport")
    store.write("Lease", doc_type="lease")

    docs = store.all()
    assert {d["name"] for d in docs} == {"Passport", "Lease"}


def test_missing_document_returns_none(tmp_path):
    store = DocumentStore(tmp_path)
    assert store.get("Nope") is None


def test_redefining_a_document_updates_in_place(tmp_path):
    store = DocumentStore(tmp_path)
    store.write("Passport", doc_type="passport", status="active")
    store.write("Passport", doc_type="passport", status="renewed")

    docs = store.all()
    assert len(docs) == 1
    assert docs[0]["status"] == "renewed"


def test_save_asset_then_read_round_trip(tmp_path):
    store = DocumentStore(tmp_path)
    rel_path = store.save_asset("Passport Scan.jpg", b"fake-jpeg-bytes")

    assert rel_path == "assets/passport-scan.jpg"
    assert store.read_asset(rel_path) == b"fake-jpeg-bytes"


def test_missing_asset_returns_none(tmp_path):
    store = DocumentStore(tmp_path)
    assert store.read_asset("assets/nope.jpg") is None


def test_no_expiry_date_stored_as_none(tmp_path):
    store = DocumentStore(tmp_path)
    store.write("Warranty Card", doc_type="warranty")

    doc = store.get("Warranty Card")
    assert doc["expiry_date"] is None
