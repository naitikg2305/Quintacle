"""2026-11-11 fixes, faked (no model is ever called):

1. .xlsx/.xls/.pptx/.ppt drops are READ deterministically by describe_drop
   (sheet names + cell rows; slide titles + text) instead of reaching the
   sorter as "Dropped file: x (no description given)".
2. An attached .md that embeds a LOCAL relative image uploaded in the same
   save gets its link rewritten to the saved asset name (safe_asset_name
   renames raft_roles.png -> raft-roles.png), so the stored link resolves.
"""
import io
import re

import openpyxl
import pytest
from fastapi.testclient import TestClient

import quintacle_core.api as api_module
from quintacle_core.nodes.kb import api as kb_api
from quintacle_core.nodes.kb import drop as drop_module
from quintacle_core.nodes.kb.drop import describe_drop
from tests.claude.files_cases import _pptx_by_hand

NO_DESC = "no description given"


def _xlsx() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Monthly 2027"
    ws.append(["Category", "Monthly ($)"])
    ws.append(["Rent", 1850])
    ws.append(["Groceries", 420])
    ws.append([None, None])
    other = wb.create_sheet("Notes")
    other.append(["Review in March"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.fixture(autouse=True)
def _no_model(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("office extraction must not call a model")

    monkeypatch.setattr(drop_module, "_describe_image", boom)
    monkeypatch.setattr(drop_module, "cloud_client", boom)


def test_xlsx_sheets_and_rows_are_read():
    out = describe_drop("budget_2027.xlsx", _xlsx())
    assert NO_DESC not in out
    assert "Sheet: Monthly 2027" in out and "Sheet: Notes" in out
    assert "Rent | 1850" in out and "Groceries | 420" in out
    assert "Review in March" in out
    assert "\n\n\n" not in out  # empty rows dropped


def test_xlsx_user_description_is_kept_first():
    out = describe_drop("budget.xlsx", _xlsx(), "my budget")
    assert out.startswith("my budget\n\n") and "Rent | 1850" in out


def test_pptx_slide_titles_and_text_are_read_without_python_pptx():
    deck = _pptx_by_hand([("Q3 review", "Local OCR pipeline"), ("Next", "Phone shell, local VLM")])
    out = describe_drop("q3_review.pptx", deck)
    assert NO_DESC not in out
    assert "Slide 1: Q3 review" in out and "Local OCR pipeline" in out
    assert "Slide 2: Next" in out and "Phone shell, local VLM" in out
    assert out.index("Slide 1") < out.index("Slide 2")


def test_pptx_slides_sort_numerically():
    deck = _pptx_by_hand([(f"T{n}", f"body {n}") for n in range(1, 12)])
    out = describe_drop("big.pptx", deck)
    assert out.index("Slide 2: T2") < out.index("Slide 10: T10")


def test_office_text_is_capped(monkeypatch):
    monkeypatch.setattr(drop_module, "_TEXT_CAP", 50)
    out = describe_drop("budget.xlsx", _xlsx())
    assert "truncated" in out and len(out) < 200


def test_renamed_ooxml_with_legacy_extension_is_read():
    assert "Rent | 1850" in describe_drop("old.xls", _xlsx())
    assert "Slide 1: Hello" in describe_drop("old.ppt", _pptx_by_hand([("Hello", "World")]))


def test_legacy_binary_gets_best_effort_strings():
    blob = b"\xd0\xcf\x11\xe0" + b"\x00" * 40 + "Root Entry".encode("utf-16-le") + b"\x01\x02" + "Car insurance".encode("utf-16-le") + b"\x00\x07Gym membership\x00"
    out = describe_drop("budget.xls", blob)
    assert "best effort" in out and "Car insurance" in out and "Gym membership" in out
    assert "Root Entry" not in out


def test_corrupt_office_file_falls_back_to_filename():
    assert describe_drop("broken.xlsx", b"PK\x03\x04garbage") == f"Dropped file: broken.xlsx ({NO_DESC})"


# ------------------------------------------------------------------ bug 2

PNG = b"\x89PNG\r\n\x1a\n" + b"7" * 64


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "DATA_DIR", tmp_path)

    def no_network(*a, **k):
        raise AssertionError("local image links must not hit the network")

    monkeypatch.setattr(kb_api.urllib.request, "urlopen", no_network)
    return TestClient(api_module.create_app()), tmp_path


def _save(c, md: str, extra: list[tuple[str, bytes, str]]):
    files = [("files", ("raft_cheatsheet.md", io.BytesIO(md.encode()), "text/markdown"))]
    files += [("files", (n, io.BytesIO(d), t)) for n, d, t in extra]
    r = c.post("/kb/entries/with-asset", data={"folder": "Notes", "title": "Raft", "content": "Raft roles"}, files=files)
    assert r.status_code == 200, r.text
    return r.json()


def test_md_relative_image_link_is_rewritten_to_saved_asset(client):
    c, root = client
    md = "# Raft\n\n![Raft roles diagram](raft_roles.png)\n\n![missing](nothere.png)\n"
    saved = _save(c, md, [("raft_roles.png", PNG, "image/png")])
    assert "assets/raft-roles.png" in saved["assets"]
    folder_dir = root / "kb" / saved["folder"]
    assert (folder_dir / "assets" / "raft-roles.png").read_bytes() == PNG

    note = (folder_dir / f"{saved['slug']}.md").read_text(encoding="utf-8")
    assert "assets/raft-roles.png" in note

    md_path = folder_dir / "assets" / "raft-cheatsheet.md"
    stored = md_path.read_text(encoding="utf-8")
    assert "![Raft roles diagram](raft-roles.png)" in stored
    assert "![missing](nothere.png)" in stored  # unmatched relative link left alone
    for link in re.findall(r"!\[[^\]]*\]\(([^)\s]+)\)", stored):
        if link != "nothere.png":
            assert (md_path.parent / link).read_bytes() == PNG


@pytest.mark.parametrize("link", ["./raft_roles.png", "images/raft_roles.png", "RAFT_ROLES.PNG", "raft%5Froles.png"])
def test_md_relative_link_variants_match_the_attached_file(client, link):
    c, root = client
    saved = _save(c, f"![d]({link})", [("raft_roles.png", PNG, "image/png")])
    stored = (root / "kb" / saved["folder"] / "assets" / "raft-cheatsheet.md").read_text(encoding="utf-8")
    assert stored == "![d](raft-roles.png)"
