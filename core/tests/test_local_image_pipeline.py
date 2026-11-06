"""Local-first image pipeline (2026-11-06): OCR -> deterministic parsers ->
local text model over OCR text -> YOLO + local VLM, gated by
perception/image_policy.py (QUINTACLE_IMAGE_PROVIDER, default local).

No real OCR engine, YOLO, VLM, Ollama or network anywhere: every stage is
stubbed, and in local mode every cloud_client() reference is patched to
FAIL — proving local never calls the cloud."""

from __future__ import annotations

import io
import sys
import types

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import quintacle_core.api as api_module
import quintacle_core.llm_dispatch as llm_dispatch
import quintacle_core.local_vlm as local_vlm
from quintacle_core.nodes import drop_router
from quintacle_core.nodes.finance import llm as finance_llm
from quintacle_core.nodes.finance.receipt_parser import guess_category, parse_date, parse_receipt
from quintacle_core.nodes.grooming import llm as grooming_llm
from quintacle_core.nodes.journal.llm import FinanceEntry
from quintacle_core.nodes.kb import drop as kb_drop
from quintacle_core.nodes.logs import nutrition_llm
from quintacle_core.nodes.wardrobe import llm as wardrobe_llm
from quintacle_core.perception import image_policy, image_router, ocr
from quintacle_core.perception.ocr import OcrLine, OcrResult, group_rows

LABEL_TEXT = """Nutrition Facts
8 servings per container
Serving size 2/3 cup (55g)
Calories 230
Total Fat 8g 10%
Saturated Fat 1g 5%
Sodium 160mg 7%
Total Carbohydrate 37g 13%
Dietary Fiber 4g 14%
Total Sugars 12g
Protein 3g
Calcium 260mg 20%"""

RECEIPT_TEXT = """TRADER JOE'S
1234 Main St Springfield IL
(555) 123-4567
11/05/2026 14:32
BANANAS 0.99
GREEK YOGURT 4.49
ALMOND BUTTER 7.99
SUBTOTAL 13.47
TAX 0.54
TOTAL 14.01
VISA ****1234 14.01
CHANGE 0.00"""


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(buf, format="PNG")
    return buf.getvalue()


def _fake_ocr(text: str | None):
    def fake(data: bytes):
        if text is None:
            return None
        lines = [OcrLine(t, (0.0, i * 20.0, 100.0, 18.0), 0.99) for i, t in enumerate(text.splitlines())]
        return OcrResult(lines=lines, text=text, engine="fake")

    return fake


def _boom(*a, **k):
    raise AssertionError("cloud was called under the local image policy")


@pytest.fixture
def no_cloud(monkeypatch):
    """Every cloud entry point an image path could reach -> AssertionError."""
    import quintacle_core.max_backend as max_backend
    from quintacle_core.nodes.documents import llm as documents_llm

    for mod in (max_backend, drop_router, nutrition_llm, wardrobe_llm, grooming_llm, kb_drop, finance_llm, llm_dispatch, documents_llm):
        if hasattr(mod, "cloud_client"):
            monkeypatch.setattr(mod, "cloud_client", _boom)
    monkeypatch.setattr(llm_dispatch, "_parse_cloud", _boom)


@pytest.fixture
def stub_ocr(monkeypatch):
    def use(text: str | None):
        monkeypatch.setattr(ocr, "ocr_image", _fake_ocr(text))

    return use


@pytest.fixture(autouse=True)
def _default_policy(monkeypatch):
    monkeypatch.delenv("QUINTACLE_IMAGE_PROVIDER", raising=False)
    monkeypatch.delenv("QUINTACLE_VISION", raising=False)
    image_policy.set_request_provider(None)
    yield
    image_policy.set_request_provider(None)


# ------------------------------------------------------------- OCR stage


def test_group_rows_merges_fragments_on_one_row():
    frags = [
        ("Total Fat 8g", 10, 100, 200, 130, 0.99),
        ("10%", 600, 102, 650, 128, 0.98),
        ("Calories", 10, 40, 200, 90, 1.0),
        ("230", 560, 42, 640, 92, 0.97),
        ("Sodium 160mg", 10, 150, 220, 178, 0.95),
    ]
    lines = group_rows(frags)
    assert [ln.text for ln in lines] == ["Calories 230", "Total Fat 8g 10%", "Sodium 160mg"]
    assert lines[1].conf == 0.98


def test_ocr_backend_selection(monkeypatch):
    monkeypatch.setenv("QUINTACLE_OCR_BACKEND", "off")
    assert ocr.ocr_backend() is None and ocr.ocr_image(b"x") is None
    monkeypatch.setenv("QUINTACLE_OCR_BACKEND", "auto")
    monkeypatch.setattr(ocr, "_rapidocr_flavor", lambda: None)
    monkeypatch.setattr(ocr.shutil, "which", lambda name: None)
    assert ocr.ocr_backend() is None  # nothing installed -> None, never an import error
    monkeypatch.setattr(ocr.shutil, "which", lambda name: "/usr/bin/tesseract")
    assert ocr.ocr_backend() == "tesseract"
    monkeypatch.setattr(ocr, "_rapidocr_flavor", lambda: "v3")
    assert ocr.ocr_backend() == "rapidocr"


def test_ocr_image_with_fake_rapidocr_v3(monkeypatch):
    """The RapidOCR 3.x output adapter (boxes/txts/scores), via a fake module."""
    fake = types.ModuleType("rapidocr")

    class _Out:
        boxes = [[[10, 100], [200, 100], [200, 130], [10, 130]], [[600, 102], [650, 102], [650, 128], [600, 128]]]
        txts = ("Total Fat 8g", "10%")
        scores = (0.99, 0.97)

    class RapidOCR:
        def __call__(self, img):
            assert isinstance(img, bytes)
            return _Out()

    fake.RapidOCR = RapidOCR
    monkeypatch.setitem(sys.modules, "rapidocr", fake)
    monkeypatch.setenv("QUINTACLE_OCR_BACKEND", "rapidocr")
    monkeypatch.setattr(ocr, "_rapid_engine", None)
    ocr.clear_cache()
    result = ocr.ocr_image(_png())
    assert result is not None and result.engine == "rapidocr"
    assert result.text == "Total Fat 8g 10%"
    ocr.clear_cache()


# ------------------------------------------------------------- router rules


@pytest.mark.parametrize(
    "text,kind",
    [
        (LABEL_TEXT, "nutrition_label"),
        ("NUTRITI0N FACTS\nServing S1ze 1 bar\nCa1ories 190", "nutrition_label"),  # OCR typos
        ("Nutrition information\nper 100g\nEnergy 1046kJ\nof which saturates 1.2 g", "nutrition_label"),
        (RECEIPT_TEXT, "receipt"),
        ("CAFE LUNA\nLatte 4.50\nCroissant 3.25\nT0TAL 7.75", "receipt"),
        ("Card ****4421\nAmount 23.10", "receipt"),
        ("RESIDENTIAL LEASE AGREEMENT\nLandlord: A. Smith\nTenant: N. G.\nPremises: 12 Oak St", "document"),
        ("PASSPORT\nNationality USA\nDate of birth 01 JAN 1990\nExpires 2030", "document"),
        ("hello world", None),
        ("", None),
    ],
)
def test_classify_text_keyword_rules(text, kind):
    assert image_router.classify_text(text) == kind


def test_nutrition_label_total_fat_is_not_a_receipt_total():
    text = "Total Fat 8g\nTotal Carbohydrate 37g\nTotal Sugars 12g\n9.99\n4.50"
    assert image_router.classify_text(text) != "receipt"


@pytest.mark.parametrize(
    "tags,kind",
    [
        (["pizza", "dining table"], "prepared_meal"),
        (["bowl", "spoon"], "prepared_meal"),
        (["handbag"], "outfit_item"),
        (["person", "handbag"], None),  # a person -> VLM decides
        (["car"], None),
        ([], None),
    ],
)
def test_classify_tags(tags, kind):
    assert image_router.classify_tags(tags) == kind


def test_parse_vlm_label():
    assert image_router.parse_vlm_label("outfit_worn") == "full_outfit"
    assert image_router.parse_vlm_label("Food.") == "prepared_meal"
    assert image_router.parse_vlm_label("I think it's a receipt") == "receipt"
    assert image_router.parse_vlm_label("¯\\_(ツ)_/¯") is None


def test_classify_local_order_ocr_then_yolo_then_vlm(monkeypatch, stub_ocr):
    calls = []
    monkeypatch.setattr(image_router, "detect_photo_tags", lambda data: calls.append("yolo") or ["person"])
    monkeypatch.setattr(image_router, "vlm_classify", lambda data, mime: calls.append("vlm") or "full_outfit")
    stub_ocr(LABEL_TEXT)
    assert image_router.classify_local(b"x", "image/png") == "nutrition_label" and calls == []  # text decided, nothing else ran
    stub_ocr("")
    assert image_router.classify_local(b"x", "image/png") == "full_outfit" and calls == ["yolo", "vlm"]


def test_classify_local_with_nothing_installed_raises(monkeypatch, stub_ocr):
    stub_ocr(None)
    monkeypatch.setattr(image_router, "detect_photo_tags", lambda data: None)
    monkeypatch.setattr(image_router, "vlm_classify", lambda data, mime: None)
    with pytest.raises(image_policy.LocalImageUnavailable):
        image_router.classify_local(b"x", "image/png")


# ------------------------------------------------------------- receipt parser


def test_receipt_parser_grocery():
    r = parse_receipt(RECEIPT_TEXT)
    assert r.merchant == "Trader Joe'S" or r.merchant.lower() == "trader joe's"
    assert r.entry_date == "2026-11-05"
    assert r.total == 14.01 and r.subtotal == 13.47 and r.tax == 0.54
    assert [i["name"] for i in r.items] == ["BANANAS", "GREEK YOGURT", "ALMOND BUTTER"]
    assert (r.category, r.kind) == ("groceries", "food")


def test_receipt_parser_noisy_amount_due_and_largest_plausible():
    text = "BLUE HERON GRILL\nNov 3, 2026\nBurger 14.00\nFries 5.00\nSub Total 19.00\nTax 1.14\nT0TAL 20.14\nTip 4.00\nAMOUNT DUE 24.14\nCash 30.00\nChange 5.86"
    r = parse_receipt(text)
    assert r.total == 24.14  # AMOUNT DUE outranks TOTAL; cash/change never count
    assert r.entry_date == "2026-11-03"
    assert r.kind == "food" and r.category == "dining"


def test_receipt_parser_value_on_next_line_and_eu_comma():
    r = parse_receipt("Bäckerei Schmidt\n05.11.2026\nBrot 3,20\nTOTAL\n3,20")
    assert r.total == 3.20 and r.entry_date == "2026-11-05"


def test_receipt_parser_subtotal_plus_tax_computed_in_code():
    r = parse_receipt("SHOP\nWidget 10.00\nSubtotal 10.00\nSales Tax 0.60")
    assert r.total == 10.60 and r.confidence["total"] == 0.6


def test_receipt_parser_no_total():
    assert parse_receipt("just some words\nno money here").total is None


@pytest.mark.parametrize(
    "text,iso",
    [("11/05/2026", "2026-11-05"), ("11-05-26", "2026-11-05"), ("2026-11-05", "2026-11-05"), ("25/12/2025", "2025-12-25"),
     ("5 November 2026", "2026-11-05"), ("Nov. 5th, 2026", "2026-11-05"), ("no date", None)],
)
def test_parse_date_formats(text, iso):
    assert parse_date(text) == iso


def test_guess_category():
    assert guess_category("Shell Oil") == ("transport", "regular")
    assert guess_category("Mystery Co") == ("", "regular")


# ------------------------------------------------------------- policy


def test_local_policy_never_calls_cloud_for_any_image_site(monkeypatch, no_cloud, stub_ocr):
    monkeypatch.setattr(image_router, "detect_photo_tags", lambda data: None)
    monkeypatch.setattr(local_vlm, "describe_images_local", lambda photos, question=None: None)
    photos = [(b"img", "image/png")]

    stub_ocr(LABEL_TEXT)
    assert drop_router.classify_image_type(b"img", "image/png") == "nutrition_label"
    est = nutrition_llm.estimate_nutrition_from_image(photos)
    assert est.from_label and est.kcal == 230 and est.basis_amount_g == 55

    stub_ocr(RECEIPT_TEXT)
    entry = drop_router.extract_finance_from_receipt(photos)
    assert entry.amount == 14.01 and entry.entry_date == "2026-11-05"

    stub_ocr("CeraVe\nFoaming Facial Cleanser\nfor normal to oily skin")
    item = grooming_llm.describe_grooming_item(photos)
    assert item.category == "skincare"

    stub_ocr(None)
    with pytest.raises(image_policy.LocalImageUnavailable, match="Redo with cloud"):
        wardrobe_llm.describe_wardrobe_item(photos)
    with pytest.raises(image_policy.LocalImageUnavailable):
        wardrobe_llm.describe_outfit_photo(photos)
    with pytest.raises(image_policy.LocalImageUnavailable):
        kb_drop.describe_images(photos)
    with pytest.raises(image_policy.LocalImageUnavailable):
        finance_llm.extract_statement_transactions(b"img", "image/png")


def test_auto_falls_back_to_cloud_and_cloud_mode_skips_local(monkeypatch, stub_ocr):
    stub_ocr(None)
    monkeypatch.setattr(image_router, "detect_photo_tags", lambda data: None)
    monkeypatch.setattr(local_vlm, "describe_images_local", lambda photos, question=None: None)
    monkeypatch.setattr(drop_router, "_classify_image_type_cloud", lambda data, mime: "receipt")
    monkeypatch.setenv("QUINTACLE_IMAGE_PROVIDER", "auto")
    assert drop_router.classify_image_type(b"x", "image/png") == "receipt"

    monkeypatch.setenv("QUINTACLE_IMAGE_PROVIDER", "cloud")
    monkeypatch.setattr(ocr, "ocr_image", _boom)  # cloud mode never even OCRs
    assert drop_router.classify_image_type(b"x", "image/png") == "receipt"


def test_private_never_cloud_even_in_auto(monkeypatch):
    monkeypatch.setenv("QUINTACLE_IMAGE_PROVIDER", "auto")
    with pytest.raises(image_policy.LocalImageUnavailable) as exc:
        image_policy.run_image_task(lambda: None, _boom, what="photo", private=True)
    assert "Redo with cloud" not in str(exc.value)


def test_request_override_beats_env(monkeypatch):
    monkeypatch.setenv("QUINTACLE_IMAGE_PROVIDER", "local")
    image_policy.set_request_provider("cloud")
    assert image_policy.image_provider() == "cloud"
    assert image_policy.image_provider(private=True) == "local"


def test_pipeline_bookkeeping():
    used = image_policy.collect_pipelines()
    providers = llm_dispatch.collect_providers()
    image_policy.run_image_task(lambda: ("x", "ocr+parser"), _boom)
    assert used == ["ocr+parser"] and providers == ["local"]
    assert image_policy.summarize_pipeline(["ocr+parser", "yolo+local-vlm"]) == "yolo+local-vlm"
    assert image_policy.summarize_pipeline(["ocr+parser", "cloud"]) == "cloud"
    assert image_policy.summarize_pipeline([]) is None


# ------------------------------------------------------------- label fallback


def test_label_missing_core_fields_goes_to_local_text_model(monkeypatch, no_cloud, stub_ocr):
    """Calories unreadable -> the OCR TEXT (never the image) goes to the
    LOCAL text model; code-read values still override the model's."""
    stub_ocr("Nutrition Facts\nServing size 1 cup (30g)\nTotal Fat 2g 3%\nSodium 120mg\nProtein 4g\n% Daily Value")
    seen = {}

    def fake_local(system, user_content, output_format, max_tokens):
        seen["content"], seen["schema"] = user_content, output_format.__name__
        return output_format(
            basis_amount_g=100, protein_g=9, carbs_g=20, fat_g=7, fiber_g=3, kcal=120,
            micros=[{"nutrient": "Iron", "amount": 2, "unit": "mg"}], suggested_name="Oat Cereal", from_label=True,
        )

    monkeypatch.setattr(llm_dispatch, "_parse_local", fake_local)
    est = nutrition_llm.estimate_nutrition_from_image([(b"img", "image/png")])
    assert isinstance(seen["content"], str) and "Total Fat 2g" in seen["content"]  # text, not image blocks
    assert est.fat_g == 2 and est.protein_g == 4  # code wins
    assert est.carbs_g == 20 and est.kcal == 120  # model filled the gaps
    assert est.basis_amount_g == 30
    assert est.field_confidence["carbs_g"] == 0.5


def test_food_photo_local_vlm_then_estimate(monkeypatch, no_cloud, stub_ocr):
    stub_ocr("")
    monkeypatch.setattr(image_router, "detect_photo_tags", lambda data: ["pizza"])
    asked = {}

    def fake_vlm(photos, question=None):
        asked["q"] = question
        return "NAME: margherita pizza slice\nGRAMS: 120"

    monkeypatch.setattr(local_vlm, "describe_images_local", fake_vlm)
    monkeypatch.setattr(nutrition_llm, "estimate_nutrition", lambda text, provider=None: nutrition_llm.NutritionEstimate(
        basis_amount_g=120, protein_g=12, carbs_g=33, fat_g=10, fiber_g=2, kcal=285, micros=[]))
    used = image_policy.collect_pipelines()
    est = nutrition_llm.estimate_nutrition_from_image([(b"img", "image/png")])
    assert "pizza" in asked["q"]  # YOLO tag rode along as a hint
    assert est.suggested_name == "margherita pizza slice" and est.basis_amount_g == 120 and not est.from_label
    assert est.kcal == 285 and used == ["yolo+local-vlm"]


def test_parse_food_answer_tolerant():
    assert nutrition_llm.parse_food_answer("**NAME:** Banana\n**GRAMS:** about 118 g") == ("Banana", 118.0)
    assert nutrition_llm.parse_food_answer("A bowl of rice, roughly 200 grams.")[1] == 200.0


# ------------------------------------------------------------- /drop end-to-end


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "DATA_DIR", tmp_path)
    monkeypatch.setattr(api_module, "perceive_photo", lambda data, mime: None)
    monkeypatch.setattr(api_module, "maybe_structure_experience", lambda *a, **k: None)
    monkeypatch.setattr(api_module, "maybe_structure_person_mention", lambda *a, **k: None)
    monkeypatch.setattr(image_router, "detect_photo_tags", lambda data: None)
    return TestClient(api_module.create_app())


def test_drop_label_photo_read_locally_with_badge(client, no_cloud, stub_ocr):
    stub_ocr(LABEL_TEXT)
    r = client.post("/drop", data={"text": ""}, files={"file": ("label.png", io.BytesIO(_png()), "image/png")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["provider_used"] == "local" and body["pipeline"] == "ocr+parser"
    [entry] = body["entries"]
    assert entry["type"] == "ingredient_preset" and entry["source"] == "label"
    assert entry["kcal"] == 230 and entry["basis_amount_g"] == 55 and entry["pipeline"] == "ocr+parser"


def test_drop_receipt_photo_read_locally(client, no_cloud, stub_ocr):
    stub_ocr(RECEIPT_TEXT)
    r = client.post("/drop", data={"text": ""}, files={"file": ("r.jpg", io.BytesIO(_png()), "image/jpeg")})
    body = r.json()
    [entry] = body["entries"]
    assert entry["type"] == "finance" and entry["amount"] == 14.01 and entry["pipeline"] == "ocr+parser"


def test_drop_unreadable_locally_offers_redo_with_cloud(client, no_cloud, stub_ocr, monkeypatch):
    stub_ocr(None)
    r = client.post("/drop", data={"text": ""}, files={"file": ("p.png", io.BytesIO(_png()), "image/png")})
    assert r.status_code == 200
    body = r.json()
    assert body["entries"] == [] and body["provider_used"] == "local"
    assert "Redo with cloud" in body["local_unavailable"]


def test_drop_redo_with_cloud_reruns_from_original_image(client, stub_ocr, monkeypatch):
    stub_ocr(None)
    monkeypatch.setattr(ocr, "ocr_image", _boom)  # provider=cloud: the local stack isn't even consulted
    monkeypatch.setattr(drop_router, "_classify_image_type_cloud", lambda data, mime: "receipt")
    seen = {}

    def cloud_receipt(photos, desc=""):
        seen["photos"] = photos
        entry = FinanceEntry(type="finance", amount=9.5, merchant="Cafe", category="dining", notes="")
        return entry

    monkeypatch.setattr(drop_router, "_extract_receipt_cloud", cloud_receipt)
    png = _png()
    r = client.post("/drop", data={"text": "", "provider": "cloud"}, files={"file": ("r.png", io.BytesIO(png), "image/png")})
    body = r.json()
    assert body["pipeline"] == "cloud" and body["provider_used"] == "cloud"
    assert seen["photos"] == [(png, "image/png")]  # the ORIGINAL bytes
    assert body["entries"][0]["pipeline"] == "cloud"


def test_other_endpoints_get_readable_422(client, stub_ocr):
    stub_ocr(None)
    r = client.post("/kb/drop", files={"file": ("p.png", io.BytesIO(_png()), "image/png")})
    assert r.status_code == 422 and r.json()["local_unavailable"] is True
