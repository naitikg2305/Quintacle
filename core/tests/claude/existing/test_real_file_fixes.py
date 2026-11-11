"""2026-11-07 fixes found by running the owner's real phone photos / PDFs
through the drop pipeline (the golden check in his testing folder):

1. local VLM: images downscaled + EXIF-oriented before Ollama, num_ctx
   raised (qwen2.5vl:3b overflowed 4096 on every 12 MP photo), and a
   garbled "????" answer retried with the output layer off the GPU.
2. an EMPTY EXIF GPS block (Samsung, location off) read as NaN coords ->
   now None everywhere, and no consumer geocodes NaN / 0,0.
3. PDFs read locally (pypdf text layer) before any cloud summary.
4. temperature 0 + fixed seed for local structured parsing and local vision.

Every network edge is stubbed; no Ollama, no cloud.
"""
from __future__ import annotations

import base64
import io
import json
import math

import httpx
import pytest
from PIL import Image, TiffImagePlugin

import quintacle_core.llm_dispatch as llm_dispatch
import quintacle_core.local_vlm as local_vlm
import quintacle_core.local_vlm.llamacpp as llamacpp_mod
import quintacle_core.local_vlm.ollama as ollama_mod
from quintacle_core.nodes.kb import drop, photo_organizer, photo_place
from quintacle_core.nodes.kb.file_meta import compose_file_meta_line as compose_line
from quintacle_core.perception import image_policy

from test_photo_place import jpeg


def _big_photo(size=(4000, 3000), orientation: int | None = 6) -> bytes:
    img = Image.new("RGB", size, "white")
    img.paste((255, 0, 0), (0, 0, size[0] // 2, size[1]))  # left half red
    exif = Image.Exif()
    if orientation:
        exif[0x0112] = orientation
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif, quality=90)
    return buf.getvalue()


# ------------------------------------------------------------- 1. VLM prep


def test_prepare_image_downscales_and_applies_exif_orientation():
    out, mime = local_vlm.prepare_image(_big_photo(), "image/jpeg")
    assert mime == "image/jpeg"
    img = Image.open(io.BytesIO(out))
    # Orientation 6 = rotate 90° CW: the 4000x3000 landscape reads 3000x4000 upright.
    assert img.size == (768, 1024)
    assert 0x0112 not in img.getexif()  # pixels rotated, tag gone
    assert img.getpixel((384, 100))[0] > 200 and img.getpixel((384, 100))[1] < 60  # red half is now on top


def test_prepare_image_keeps_small_images_small_and_flattens_alpha():
    img = Image.new("RGBA", (200, 100), (0, 0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    out, mime = local_vlm.prepare_image(buf.getvalue(), "image/png")
    got = Image.open(io.BytesIO(out))
    assert mime == "image/jpeg" and got.size == (200, 100) and got.mode == "RGB"
    assert got.getpixel((10, 10)) == (255, 255, 255)


def test_prepare_image_passes_non_images_through():
    assert local_vlm.prepare_image(b"not an image", "image/jpeg") == (b"not an image", "image/jpeg")


def test_prepare_image_max_side_env(monkeypatch):
    monkeypatch.setenv("QUINTACLE_VISION_MAX_SIDE", "512")
    out, _ = local_vlm.prepare_image(_big_photo(orientation=None))
    assert Image.open(io.BytesIO(out)).size == (512, 384)


class _Resp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload
        self.text = ""

    def json(self):
        return self._payload


@pytest.fixture
def ollama_calls(monkeypatch):
    monkeypatch.delenv("QUINTACLE_OLLAMA_URL", raising=False)
    monkeypatch.delenv("QUINTACLE_VISION_MODEL", raising=False)
    monkeypatch.delenv("QUINTACLE_VISION_NUM_GPU", raising=False)
    monkeypatch.setattr(ollama_mod, "_GPU_FALLBACK", {})
    calls: list[tuple[str, dict]] = []
    answers: list = []

    def fake_post(url, json=None, timeout=None):
        calls.append((url, json))
        if url.endswith("/api/show"):
            return _Resp(payload={"model_info": {"general.architecture": "qwen25vl", "qwen25vl.block_count": 36}})
        return answers.pop(0)

    monkeypatch.setattr(httpx, "post", fake_post)
    return calls, answers


def test_ollama_request_sends_downscaled_image_with_ctx_and_greedy_options(ollama_calls):
    calls, answers = ollama_calls
    answers.append(_Resp(payload={"message": {"content": "peppers on a board"}}))
    assert ollama_mod.describe_images_local([(_big_photo(), "image/jpeg")]) == "peppers on a board"
    (url, payload), = calls
    assert payload["options"] == {"num_ctx": 8192, "temperature": 0, "seed": local_vlm.VLM_SEED}
    sent = Image.open(io.BytesIO(base64.b64decode(payload["messages"][0]["images"][0])))
    assert max(sent.size) == 1024


def test_ollama_garbled_answer_retries_with_output_layer_off_gpu_and_remembers(ollama_calls):
    calls, answers = ollama_calls
    answers += [
        _Resp(status_code=500, payload={"error": "prediction aborted, token repeat limit reached"}),
        _Resp(payload={"message": {"content": "a nutrition label"}}),
        _Resp(payload={"message": {"content": "an onion"}}),
    ]
    assert ollama_mod.describe_images_local([(b"x", "image/jpeg")]) == "a nutrition label"
    chats = [p for u, p in calls if u.endswith("/api/chat")]
    assert "num_gpu" not in chats[0]["options"] and chats[1]["options"]["num_gpu"] == 36
    # Next photo goes straight to the working setting — no failed first try.
    assert ollama_mod.describe_images_local([(b"y", "image/jpeg")]) == "an onion"
    chats = [p for u, p in calls if u.endswith("/api/chat")]
    assert len(chats) == 3 and chats[2]["options"]["num_gpu"] == 36


def test_ollama_question_marks_only_is_garbage_not_a_description(ollama_calls):
    calls, answers = ollama_calls
    answers += [_Resp(payload={"message": {"content": "????????"}}), _Resp(payload={"message": {"content": "??????"}})]
    assert ollama_mod.describe_images_local([(b"x", "image/jpeg")]) is None
    assert ollama_mod._GPU_FALLBACK == {}  # the retry didn't help either — nothing remembered


def test_ollama_num_gpu_env_pins_it(ollama_calls, monkeypatch):
    calls, answers = ollama_calls
    monkeypatch.setenv("QUINTACLE_VISION_NUM_GPU", "0")
    answers.append(_Resp(payload={"message": {"content": "ok"}}))
    assert ollama_mod.describe_images_local([(b"x", "image/jpeg")]) == "ok"
    assert calls[0][1]["options"]["num_gpu"] == 0


def test_llamacpp_request_is_downscaled_and_greedy(monkeypatch):
    seen = {}

    def fake_post(url, json=None, timeout=None):
        seen["json"] = json
        return _Resp(payload={"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr(httpx, "post", fake_post)
    assert llamacpp_mod.describe_images_llamacpp([(_big_photo(), "image/png")]) == "ok"
    assert seen["json"]["temperature"] == 0 and seen["json"]["seed"] == local_vlm.VLM_SEED
    url = seen["json"]["messages"][0]["content"][0]["image_url"]["url"]
    assert url.startswith("data:image/jpeg;base64,")
    assert max(Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))).size) == 1024


# ------------------------------------------------------------- 2. empty GPS


def _empty_gps_jpeg() -> bytes:
    """What a Samsung photo with location off carries: a GPSInfo IFD whose
    rationals are all 0/0 — Pillow decodes those as NaN."""
    zero = TiffImagePlugin.IFDRational(0, 0)
    img = Image.new("RGB", (4, 4), "red")
    exif = Image.Exif()
    exif[306] = "2026:10:15 20:21:31"
    exif[0x8825] = {1: "", 2: (zero, zero, zero), 3: "", 4: (zero, zero, zero)}
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif)
    return buf.getvalue()


def test_empty_gps_block_reads_as_no_location():
    data = _empty_gps_jpeg()
    gps = Image.open(io.BytesIO(data)).getexif().get_ifd(0x8825)
    assert math.isnan(drop._dms_to_decimal(gps[2], "N"))  # the raw read really is NaN
    assert drop.extract_photo_location(data) is None
    assert drop.extract_photo_location(jpeg(gps=(0.0, 0.0))) is None  # null island = blank block
    assert drop.extract_photo_location(jpeg()) == {"lat": pytest.approx(48.2082, abs=1e-3), "lon": pytest.approx(16.3738, abs=1e-3)}


@pytest.mark.parametrize(
    "loc",
    [{"lat": float("nan"), "lon": float("nan")}, {"lat": float("inf"), "lon": 1.0}, {"lat": 0, "lon": 0},
     {"lat": 91, "lon": 0}, {"lat": None, "lon": 3}, {"lat": "x", "lon": 3}, None, "48,16"],
)
def test_clean_location_rejects_bad_coordinates(loc):
    assert drop.clean_location(loc) is None


def test_no_consumer_geocodes_nan(monkeypatch, tmp_path):
    def geocode_must_not_run(lat, lon):
        raise AssertionError(f"geocode called with {lat}, {lon}")

    monkeypatch.setattr(photo_organizer, "geocode", geocode_must_not_run)
    nan = {"lat": float("nan"), "lon": float("nan")}
    pp = photo_place.resolve_photo_place([("a.jpg", _empty_gps_jpeg())], private=False, cache_path=tmp_path / "geo.json", fallback_location=nan)
    assert pp.location is None and pp.place is None
    assert pp.line is not None and "nan" not in pp.line  # just the capture time
    assert photo_place.cached_geocode(float("nan"), float("nan"), tmp_path / "geo.json") is None
    assert photo_place.compose_place_line(None, nan, None) is None
    from datetime import date

    assert photo_organizer.compute_photo_folder(date(2026, 10, 15), nan, None, ["United States"]) == "Media/Photos/2026/October"
    line = compose_line({"kind": "photo", "filename": "a.jpg", "size": 10, "location": nan})
    assert "nan" not in line


def test_geocode_itself_refuses_nan_before_any_cloud_call(monkeypatch):
    monkeypatch.setattr(photo_organizer, "cloud_client", lambda: (_ for _ in ()).throw(AssertionError("cloud")))
    with pytest.raises(ValueError):
        photo_organizer.geocode(float("nan"), float("nan"))


# ------------------------------------------------------------- 3. local PDF


def _text_pdf(text: str) -> bytes:
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue()


def _scanned_pdf() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (200, 260), "white").save(buf, format="PDF")
    return buf.getvalue()


ITINERARY = "Day 1 Budapest then Day 3 Vienna by train then Day 6 Prague, nothing booked yet"


def _cloud_pdf_must_not_run(data):
    raise AssertionError("cloud PDF summary must not run")


def test_pdf_with_text_layer_is_read_locally(monkeypatch):
    pytest.importorskip("pypdf")
    monkeypatch.setattr(drop, "_describe_pdf_cloud", _cloud_pdf_must_not_run)
    out = drop.describe_drop("itinerary.pdf", _text_pdf(ITINERARY), "trip plan")
    assert out.startswith("trip plan\n\n") and ITINERARY in out


def test_pdf_text_is_capped_like_text_files(monkeypatch):
    pytest.importorskip("pypdf")
    monkeypatch.setattr(drop, "_extract_pdf_text", lambda data: "word " * 10_000)
    monkeypatch.setattr(drop, "_describe_pdf_cloud", _cloud_pdf_must_not_run)
    out = drop._describe_pdf(b"%PDF")
    assert len(out) < drop._TEXT_CAP + 100 and "truncated" in out


def test_scanned_pdf_local_mode_asks_for_redo_with_cloud(monkeypatch):
    monkeypatch.delenv("QUINTACLE_IMAGE_PROVIDER", raising=False)
    monkeypatch.setattr(drop, "_describe_pdf_cloud", _cloud_pdf_must_not_run)
    with pytest.raises(image_policy.LocalImageUnavailable, match="Redo with cloud"):
        drop.describe_drop("scan.pdf", _scanned_pdf())


def test_scanned_pdf_is_ocrd_locally_when_ocr_is_available(monkeypatch):
    pytest.importorskip("pypdf")
    from quintacle_core.perception import ocr
    from quintacle_core.perception.ocr import OcrResult

    monkeypatch.setattr(ocr, "ocr_image", lambda data: OcrResult(lines=[], text=ITINERARY, engine="stub", image_size=(1, 1)))
    monkeypatch.setattr(drop, "_describe_pdf_cloud", _cloud_pdf_must_not_run)
    used = image_policy.collect_pipelines()
    assert drop.describe_drop("scan.pdf", _scanned_pdf()) == ITINERARY
    assert used == ["ocr+parser"]


def test_scanned_pdf_auto_falls_back_and_cloud_redo_skips_local(monkeypatch):
    monkeypatch.setattr(drop, "_describe_pdf_cloud", lambda data: "cloud summary")
    monkeypatch.setenv("QUINTACLE_IMAGE_PROVIDER", "auto")
    assert drop.describe_drop("scan.pdf", _scanned_pdf()) == "cloud summary"
    # Redo with cloud = a step back to the ORIGINAL file, no local read first.
    monkeypatch.setenv("QUINTACLE_IMAGE_PROVIDER", "cloud")
    monkeypatch.setattr(drop, "_extract_pdf_text", lambda data: (_ for _ in ()).throw(AssertionError("local read")))
    assert drop.describe_drop("itinerary.pdf", _text_pdf(ITINERARY)) == "cloud summary"


def test_pypdf_missing_degrades_to_no_text(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def no_pypdf(name, *args, **kwargs):
        if name == "pypdf":
            raise ImportError("no pypdf")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_pypdf)
    assert drop._extract_pdf_text(_text_pdf(ITINERARY)) == ""


# ------------------------------------------------------------- 4. determinism


def test_local_structured_parse_is_greedy_with_fixed_seed(monkeypatch):
    from pydantic import BaseModel

    class Fruit(BaseModel):
        name: str

    seen = []

    class _R(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        seen.append(json.loads(req.data.decode()))
        return _R(json.dumps({"message": {"content": '{"name": "apple"}'}}).encode())

    monkeypatch.setattr(llm_dispatch.urllib.request, "urlopen", fake_urlopen)
    assert llm_dispatch.parse_structured("s", "u", Fruit, provider="local").parsed.name == "apple"
    opts = seen[0]["options"]
    assert opts["temperature"] == 0 and opts["seed"] == llm_dispatch.PARSE_SEED


def test_usda_pick_goes_through_the_greedy_local_parse(monkeypatch):
    """The USDA candidate picker routes through parse_structured -> _parse_local,
    so it inherits temperature 0 + seed (asserted above)."""
    from quintacle_core.nutrition_db import store as usda_store

    seen = {}

    def fake_parse(system, user, fmt, *, provider=None, max_tokens=4096):
        seen["called"] = True
        return llm_dispatch.ParseResult(fmt(choice=2), "local")

    monkeypatch.setattr(llm_dispatch, "parse_structured", fake_parse)
    cands = [{"description": "Orange peel, raw", "category": "Fruits", "score": 0.5}, {"description": "Oranges, raw", "category": "Fruits", "score": 0.49}]
    assert usda_store.pick_candidate("orange", cands, provider="local")["description"] == "Oranges, raw"
    assert seen["called"]
