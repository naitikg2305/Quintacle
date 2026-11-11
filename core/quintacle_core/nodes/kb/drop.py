from __future__ import annotations

import base64
import io
import logging
import math
import os
import re
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from datetime import date, datetime

import anthropic
from docx import Document
from PIL import Image

from ...llm_config import DEFAULT_MODEL
from ..vision import image_content_blocks, vision_prompt
from ...max_backend import cloud_client

logger = logging.getLogger(__name__)

_IMAGE_MIME = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "gif": "image/gif",
    "webp": "image/webp",
}

# Claude has no native video input — the only way to "watch" one is to pull
# out a handful of still frames and caption those, same as the docx-is-
# really-a-photo fallback below. Not real motion/audio understanding, just
# enough visual sampling to describe what the video is of.
_VIDEO_EXT = {"mp4", "webm", "mov", "m4v"}
_VIDEO_SAMPLE_FRAMES = 4

# Below this many real characters, a docx's paragraph text isn't enough to
# describe it from — most commonly because the docx is really just a scanned
# photo/screenshot pasted in (a phone "scan to Word" flow), which
# python-docx's paragraph text never sees at all.
_DOCX_MIN_TEXT_LEN = 30

# File types with no meaningful text/visual content an LLM can read (e.g. STL
# geometry) — dropped as-is, described only by whatever the user typed.
_NO_EXTRACTION = {"stl", "obj", "3mf"}


def _extension(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def is_image(filename: str) -> bool:
    return _extension(filename) in _IMAGE_MIME


def describe_images(
    photos: list[tuple[bytes, str]], question: str | None = None, *, provider: str | None = None, private: bool = False
) -> str:
    """One vision call over one-or-more (bytes, mime) photos — the same
    machinery every drop-time description already runs on, exposed for
    on-demand "look at this photo again, now" calls (/kb/asset/describe,
    the MCP describe_photo tool). With `question` given, the call answers
    that question about the photo(s) instead of generically describing
    them.

    Provider switch — QUINTACLE_VISION, read per call:
      cloud (default)  metered Anthropic call on DEFAULT_MODEL, exactly the
                       pre-switch behavior; callers decide when that spend
                       is worth it.
      local            a small VLM via Ollama on localhost (local_vlm/);
                       raises RuntimeError rather than silently billing the
                       cloud if local vision is unavailable.
      auto             try local first, fall back to cloud with a log line.

    The dispatch lives here, in the one shared function, so every call site
    (drop-time description, /kb/asset/describe, MCP describe_photo)
    inherits the switch without knowing it exists.

    2026-11-06 — LOCAL BY DEFAULT (the owner's "it should always have been
    local"). The mode now resolves: per-request override (Redo with cloud)
    > QUINTACLE_IMAGE_PROVIDER > the legacy QUINTACLE_VISION (still honored
    when set) > "local". The local path also folds in local OCR text (a
    document/sign/whiteboard reads better as text than as a caption) and, if
    the VLM is down, still answers from OCR text + YOLO tags. `private`
    pins local regardless (a private note's asset never reaches cloud).

    2026-11-11 — image_policy.image_provider() is now the single source of
    truth: this function no longer reads QUINTACLE_VISION directly (the
    "Provider switch" list above is history). The legacy var is still
    honored there, with a one-time deprecation warning, but legacy `cloud`
    maps to `auto` — so a stale QUINTACLE_VISION=cloud can no longer make
    image description cloud-first. Local stays the default."""
    from ...perception import image_policy

    mode = image_policy.image_provider(provider, private=private)
    if mode in ("local", "auto"):
        local = _describe_images_local(photos, question)
        if local is not None:
            description, pipeline = local
            image_policy.record_pipeline(pipeline)
            return description
        if mode == "local":
            raise image_policy.LocalImageUnavailable(
                "couldn't read this image locally — local vision is unavailable (is Ollama running with "
                "the vision model pulled? see logs from quintacle_core.local_vlm) and local OCR found no text"
                + ("" if private else " — Redo with cloud?"),
                what="image",
            )
        logger.warning("image provider auto: local VLM unavailable, falling back to cloud (%s)", DEFAULT_MODEL)
    description = _describe_images_cloud(photos, question)
    image_policy.record_pipeline("cloud")
    return description


def _describe_images_local(photos: list[tuple[bytes, str]], question: str | None = None) -> tuple[str, str] | None:
    """Local VLM caption + local OCR text; OCR + YOLO tags alone when the
    VLM is down. None when the local stack has nothing at all."""
    from ...local_vlm import describe_images_local  # lazy: cloud path never touches it
    from ...perception.image_router import detect_photo_tags
    from ...perception.ocr import ocr_image

    caption = describe_images_local(photos, question)
    if question and question.strip():
        # A specific question needs an actual answer, not an OCR dump.
        return (caption, "yolo+local-vlm") if caption is not None else None
    texts = []
    for data, _mime in photos:
        try:
            r = ocr_image(data)
        except ValueError:
            r = None
        if r is not None and r.word_count >= 3:
            texts.append(r.text)
    ocr_text = "\n".join(texts).strip()
    if caption is not None:
        if ocr_text:
            return f"{caption}\n\nText in the image (local OCR):\n{ocr_text}", "yolo+local-vlm"
        return caption, "yolo+local-vlm"
    tags = detect_photo_tags(photos[0][0]) or []
    if not ocr_text and not tags:
        return None
    parts = []
    if tags:
        parts.append(f"Photo — objects detected locally: {', '.join(tags)}.")
    if ocr_text:
        parts.append(f"Text in the image (local OCR):\n{ocr_text}")
    return "\n\n".join(parts), ("ocr+parser" if ocr_text else "yolo")


def _describe_images_cloud(photos: list[tuple[bytes, str]], question: str | None = None) -> str:
    """The original metered Anthropic vision call — one real API call on
    DEFAULT_MODEL every time."""
    client = cloud_client()
    prompt = vision_prompt(len(photos), question)
    response = client.messages.create(
        model=DEFAULT_MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": [*image_content_blocks(photos), {"type": "text", "text": prompt}]}],
    )
    return next((b.text for b in response.content if b.type == "text"), "")


def _describe_image(photos: list[tuple[bytes, str]]) -> str:
    return describe_images(photos)


# 2026-11-07: a PDF with at least this many letters/digits in its text layer
# is READ locally (like a .txt) — fewer means a scan / image-only PDF.
_PDF_MIN_TEXT_CHARS = 40
_PDF_OCR_MAX_PAGES = 10


def _extract_pdf_text(data: bytes) -> str:
    """The PDF's own text layer via pypdf (pure python, Termux-safe; lazy so
    a phone install that hasn't picked it up yet degrades to "no text").
    Pages joined with blank lines; "" on any failure."""
    try:
        from pypdf import PdfReader
    except ImportError:
        logger.warning("pypdf not installed — PDF text can't be read locally (pip install -r core/requirements.txt)")
        return ""
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception:
                return ""
        pages = []
        for page in reader.pages:
            try:
                pages.append((page.extract_text() or "").strip())
            except Exception as exc:  # one bad page must not lose the rest
                logger.debug("pdf page text extraction failed: %s", exc)
        return "\n\n".join(p for p in pages if p)
    except Exception as exc:
        logger.warning("pdf text extraction failed: %s", exc)
        return ""


def _ocr_pdf_images(data: bytes) -> str:
    """A scanned PDF is usually one embedded JPEG per page — pypdf hands
    those out without any rasterizer, so local OCR can read them. "" when
    pypdf/OCR is unavailable or nothing reads."""
    try:
        from pypdf import PdfReader

        from ...perception.ocr import ocr_image
    except ImportError:
        return ""
    texts: list[str] = []
    try:
        reader = PdfReader(io.BytesIO(data))
        for page in list(reader.pages)[:_PDF_OCR_MAX_PAGES]:
            for img in page.images:
                try:
                    r = ocr_image(img.data)
                except Exception:
                    r = None
                if r is None:
                    if not texts:
                        return ""  # no OCR backend at all — don't walk every image
                    continue
                if r.text.strip():
                    texts.append(r.text.strip())
    except Exception as exc:
        logger.warning("pdf image OCR failed: %s", exc)
    return "\n\n".join(texts)


def _meaningful(text: str) -> int:
    return sum(ch.isalnum() for ch in text)


def _describe_pdf(data: bytes) -> str:
    """2026-11-07 — local first. Text layer (pypdf) → handed to the sorter
    as-is, capped like _read_text; a scan → local OCR of its page images;
    only then the cloud summary, and only as the image policy allows
    (local mode raises "couldn't read this PDF locally — Redo with cloud?",
    auto falls back, cloud / Redo-with-cloud goes straight there)."""
    from ...perception import image_policy

    if image_policy.image_provider() != "cloud":
        text = _extract_pdf_text(data)
        if _meaningful(text) >= _PDF_MIN_TEXT_CHARS:
            return _cap_text(text, len(data))

    def local():
        ocr_text = _ocr_pdf_images(data)
        if _meaningful(ocr_text) >= _PDF_MIN_TEXT_CHARS:
            return _cap_text(ocr_text, len(data)), "ocr+parser"
        raise image_policy.LocalImageUnavailable("no text layer and local OCR read nothing", what="PDF")

    return image_policy.run_image_task(local, lambda: _describe_pdf_cloud(data), what="PDF")


def _describe_pdf_cloud(data: bytes) -> str:
    client = cloud_client()
    response = client.messages.create(
        model=DEFAULT_MODEL,
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": base64.standard_b64encode(data).decode()}},
                    {"type": "text", "text": "Summarize this document in a few sentences, for filing into a personal knowledge base."},
                ],
            }
        ],
    )
    return next((b.text for b in response.content if b.type == "text"), "")


def _extract_docx_text(data: bytes) -> str:
    doc = Document(io.BytesIO(data))
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


def _extract_docx_images(data: bytes) -> list[tuple[bytes, str]]:
    """Raster images embedded in the docx (word/media/) — read straight out
    of the .docx zip archive rather than through python-docx, which exposes
    no direct way to get an inline shape's actual image bytes."""
    images = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for name in sorted(z.namelist()):
            if not name.startswith("word/media/"):
                continue
            ext = name.rsplit(".", 1)[-1].lower()
            mime = _IMAGE_MIME.get(ext)
            if mime:
                images.append((z.read(name), mime))
    return images


def _describe_docx(data: bytes) -> str:
    text = _extract_docx_text(data)
    if len(text) >= _DOCX_MIN_TEXT_LEN:
        return text
    # Little/no real paragraph text — most likely a scanned photo pasted
    # into a Word wrapper. Fall back to captioning the embedded image the
    # same way a direct photo upload would be described.
    images = _extract_docx_images(data)
    if not images:
        return text
    caption = _describe_image([images[0]])
    return f"{text}\n\n{caption}".strip() if text else caption


def _extract_video_frames(data: bytes, count: int = _VIDEO_SAMPLE_FRAMES) -> list[tuple[bytes, str]]:
    """OpenCV needs a real file path, not in-memory bytes — write to a temp
    file, sample `count` frames evenly across the duration, encode each as
    JPEG. Returns [] for anything that fails to open (corrupt/unsupported
    container) rather than raising, so a bad video degrades to "no visual
    description" instead of a 500. cv2 imports lazily — on Termux there's no
    opencv wheel and the pkg build can be unavailable per mirror; a phone
    install without it should lose video description, not the whole API."""
    try:
        import cv2
    except ImportError:
        return []
    with tempfile.NamedTemporaryFile(suffix=".mp4") as tmp:
        tmp.write(data)
        tmp.flush()
        cap = cv2.VideoCapture(tmp.name)
        if not cap.isOpened():
            return []
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total_frames <= 0:
            cap.release()
            return []
        indices = [round((i + 1) * total_frames / (count + 1)) for i in range(count)]
        frames = []
        for idx in indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ok, frame = cap.read()
            if not ok:
                continue
            ok, buf = cv2.imencode(".jpg", frame)
            if ok:
                frames.append((buf.tobytes(), "image/jpeg"))
        cap.release()
        return frames


_VIDEO_QUESTION = (
    "These are {n} frames sampled evenly across a video, in order. Describe what the video appears to "
    "show in a few sentences — you're seeing snapshots, not motion or audio."
)


def _describe_video(data: bytes) -> str:
    """Frames -> one description. 2026-11-06: frames are images, so the
    image policy applies — the local VLM reads them (default), cloud only
    for provider=cloud or the auto fallback."""
    frames = _extract_video_frames(data)
    if not frames:
        return ""
    from ...perception.image_policy import run_image_task

    def local():
        from ...local_vlm import describe_images_local

        text = describe_images_local(frames, _VIDEO_QUESTION.format(n=len(frames)))
        return (text, "yolo+local-vlm") if text else None

    return run_image_task(local, lambda: _describe_video_cloud(frames), what="video")


def _describe_video_cloud(frames: list[tuple[bytes, str]]) -> str:
    client = cloud_client()
    response = client.messages.create(
        model=DEFAULT_MODEL,
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": [
                    *image_content_blocks(frames),
                    {
                        "type": "text",
                        "text": (
                            f"These are {len(frames)} frames sampled evenly across a video, in order. "
                            "Describe what the video appears to show in a few sentences, for filing "
                            "into a personal knowledge base — you're seeing snapshots, not motion or "
                            "audio, so describe what's visible rather than guessing at action between "
                            "frames."
                        ),
                    },
                ],
            }
        ],
    )
    return next((b.text for b in response.content if b.type == "text"), "")


def _exif_date_candidates(data: bytes) -> list:
    try:
        img = Image.open(io.BytesIO(data))
        exif = img.getexif()
        candidates = []
        # DateTimeOriginal/DateTimeDigitized live in the Exif sub-IFD
        # (0x8769); plain DateTime is in the base IFD — check both.
        try:
            exif_ifd = exif.get_ifd(0x8769)
            for tag in (36867, 36868):  # DateTimeOriginal, DateTimeDigitized
                if tag in exif_ifd:
                    candidates.append(exif_ifd[tag])
        except Exception:
            pass
        if 306 in exif:  # DateTime
            candidates.append(exif[306])
        return candidates
    except Exception:
        return []


def extract_photo_date(data: bytes) -> date | None:
    """Deterministic — reads the photo's own embedded capture date (EXIF),
    no AI involved. Lets a batch of trip photos connect to the day you
    actually journaled about, without any manual date-sorting. Returns None
    for anything with no EXIF date (screenshots, scans, stripped images)."""
    for raw in _exif_date_candidates(data):
        try:
            return datetime.strptime(str(raw).split(" ")[0], "%Y:%m:%d").date()
        except ValueError:
            continue
    return None


def extract_photo_datetime(data: bytes) -> datetime | None:
    """Same EXIF read as extract_photo_date but keeping the capture TIME —
    the photo auto-journal line leads with it ("📷 2:14 PM — ..."). Returns
    None when EXIF carries no full date+time (a date-only tag still dates
    the journal entry via extract_photo_date; it just gets no clock time)."""
    for raw in _exif_date_candidates(data):
        try:
            return datetime.strptime(str(raw).strip(), "%Y:%m:%d %H:%M:%S")
        except ValueError:
            continue
    return None


def _dms_to_decimal(dms, ref: str) -> float:
    degrees, minutes, seconds = (float(v) for v in dms)
    value = degrees + minutes / 60 + seconds / 3600
    return -value if ref in ("S", "W") else value


def valid_coords(lat, lon) -> bool:
    """True only for real coordinates: finite numbers in range and not the
    0,0 "null island" a blank GPS block decodes to. 2026-11-07: Samsung
    photos taken with location off carry an EMPTY GPSInfo block whose
    rationals are 0/0 — Pillow reads those as NaN, so every one of them
    used to come out as {lat: NaN, lon: NaN} and trigger a cloud geocode."""
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return False
    if not (math.isfinite(lat) and math.isfinite(lon)):
        return False
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return False
    return not (lat == 0 and lon == 0)


def clean_location(location) -> dict | None:
    """{lat, lon} when `location` holds valid coordinates, else None — the
    guard every consumer (photo place line, place graph, geocode, photo
    folder) runs before trusting a stored or extracted location."""
    if not isinstance(location, dict):
        return None
    lat, lon = location.get("lat"), location.get("lon")
    if not valid_coords(lat, lon):
        return None
    return {"lat": float(lat), "lon": float(lon)}


def extract_photo_location(data: bytes) -> dict | None:
    """Deterministic — reads the photo's embedded GPS coordinates (EXIF
    GPSInfo), no AI. Groundwork for eventually answering "what was I doing
    on April 10" by combining this + the journal entry + the photo itself —
    that query feature isn't built yet, this just makes sure the data is
    captured now instead of lost. Returns None if there's no GPS tag."""
    try:
        img = Image.open(io.BytesIO(data))
        gps = img.getexif().get_ifd(0x8825)  # GPSInfo IFD
        if not gps or 2 not in gps or 4 not in gps:
            return None
        lat = _dms_to_decimal(gps[2], gps.get(1, "N"))  # GPSLatitude, GPSLatitudeRef
        lon = _dms_to_decimal(gps[4], gps.get(3, "E"))  # GPSLongitude, GPSLongitudeRef
        if not valid_coords(lat, lon):  # empty GPS block -> NaN / 0,0 (2026-11-07)
            return None
        return {"lat": round(lat, 6), "lon": round(lon, 6)}
    except Exception:
        return None


# Plain-text formats are READ, not described (2026-11-05 fix): a chat answer
# turned into a .md file and then "Sort with AI" used to reach the sorter as
# "Dropped file: x.md (no description given)" — no branch handled text at all.
# Decoded as UTF-8 (lossy), capped so a huge log can't blow the prompt.
_TEXT_EXT = {
    "md", "markdown", "txt", "text", "csv", "tsv", "json", "jsonl", "yaml", "yml", "toml", "ini", "cfg",
    "html", "htm", "xml", "log", "rst", "tex", "py", "js", "ts", "tsx", "jsx", "sh", "sql", "css",
}
_TEXT_CAP = 20_000


def _read_text(data: bytes) -> str:
    return _cap_text(data.decode("utf-8", errors="replace").strip(), len(data))


def _cap_text(text: str, total_bytes: int) -> str:
    if len(text) > _TEXT_CAP:
        text = text[:_TEXT_CAP] + f"\n\n[…truncated — {total_bytes:,} bytes total]"
    return text


# Office spreadsheets/decks are READ, not described (2026-11-11 fix): a
# dropped budget_2027.xlsx or q3_review.pptx reached the sorter as "Dropped
# file: … (no description given)" — no branch handled them, the same bug .md
# and .docx had. Deterministic extraction, capped like _read_text:
#   xlsx → openpyxl (already a core requirement, pure Python, phone-safe) via
#          spreadsheet.read_spreadsheet: "Sheet: <name>" + one " | "-joined row per line
#   pptx → stdlib zipfile + ElementTree over ppt/slides/slideN.xml (no
#          python-pptx dependency): "Slide N: <title>" + that slide's other text
#   xls / ppt (legacy binary OLE) → if it's really OOXML renamed, the readers
#          above; otherwise best-effort printable-string recovery, labelled so.
_SHEET_EXT = {"xlsx", "xlsm", "xls"}
_DECK_EXT = {"pptx", "pptm", "ppt"}
_DML_NS = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_PML_NS = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
_OLE_NOISE = {
    "root entry", "workbook", "book", "summaryinformation", "documentsummaryinformation",
    "powerpoint document", "current user", "pictures", "compobj", "calibri", "arial",
    "times new roman", "microsoft excel", "microsoft powerpoint", "office theme", "sheet1",
    "general", "default design",
}


def _is_zip(data: bytes) -> bool:
    return data[:4] == b"PK\x03\x04"


def _extract_xlsx_text(data: bytes) -> str:
    from .spreadsheet import read_spreadsheet

    out: list[str] = []
    for sheet in read_spreadsheet(data)["sheets"]:
        rows = [" | ".join(c.strip() for c in row).strip(" |") for row in sheet["rows"]]
        rows = [r for r in rows if r]
        if not rows:
            continue
        out += [f"Sheet: {sheet['name']}", *rows, ""]
    return "\n".join(out).strip()


def _slide_number(name: str) -> int:
    digits = "".join(ch for ch in name.rsplit("/", 1)[-1] if ch.isdigit())
    return int(digits) if digits else 0


def _extract_pptx_text(data: bytes) -> str:
    out: list[str] = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        slides = sorted(
            (n for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
            key=_slide_number,
        )
        for name in slides:
            root = ET.fromstring(z.read(name))
            title, texts = "", []
            for sp in root.iter(f"{_PML_NS}sp"):
                ph = sp.find(f"{_PML_NS}nvSpPr/{_PML_NS}nvPr/{_PML_NS}ph")
                is_title = ph is not None and ph.get("type") in ("title", "ctrTitle")
                paras = []
                for para in sp.iter(f"{_DML_NS}p"):
                    line = "".join(t.text or "" for t in para.iter(f"{_DML_NS}t")).strip()
                    if line:
                        paras.append(line)
                if is_title and not title:
                    title = " ".join(paras)
                else:
                    texts.extend(paras)
            if not (title or texts):
                continue
            n = _slide_number(name)
            out += [f"Slide {n}: {title}" if title else f"Slide {n}", *texts, ""]
    return "\n".join(out).strip()


def _legacy_office_strings(data: bytes) -> str:
    """Printable runs out of an old binary .xls/.ppt (UTF-16LE and 8-bit) —
    no parser dependency; noisy but deterministic, and far better than the
    filename alone. OLE stream names / font names are dropped, dupes folded."""
    found = [r.decode("utf-16-le", errors="ignore") for r in re.findall(rb"(?:[\x20-\x7e]\x00){3,}", data)]
    found += [r.decode("latin-1") for r in re.findall(rb"[\x20-\x7e]{4,}", data)]
    seen: set[str] = set()
    keep: list[str] = []
    for s in found:
        s = s.strip()
        key = s.lower()
        if len(s) < 3 or key in seen or key in _OLE_NOISE or not re.search(r"[A-Za-z]{2}", s):
            continue
        seen.add(key)
        keep.append(s)
    return "\n".join(keep)


def _describe_office(ext: str, data: bytes) -> str:
    """xlsx/pptx (and legacy xls/ppt) → capped plain text; never raises."""
    try:
        if _is_zip(data):
            text = _extract_xlsx_text(data) if ext in _SHEET_EXT else _extract_pptx_text(data)
        else:
            text = _legacy_office_strings(data)
            if text:
                text = f"Text recovered from a legacy .{ext} file (best effort):\n{text}"
    except Exception as exc:  # corrupt file → no extraction (filename fallback), not a 500
        logger.warning("office extraction failed for .%s: %s", ext, exc)
        return ""
    return _cap_text(text, len(data))


def describe_drop(
    filename: str,
    data: bytes,
    user_description: str = "",
    filename2: str | None = None,
    data2: bytes | None = None,
) -> str:
    """One text description to feed the existing suggest_kb_entry() sort
    step — same function text drops already use, so a dropped file gets
    filed by the exact same logic, not a parallel path. A second file only
    combines with the first when both are images (e.g. front + back of the
    same thing) — a second PDF/DOCX would be a separate, unrelated document,
    not a second view of this one, so it's ignored rather than guessed at."""
    ext = _extension(filename)
    ext2 = _extension(filename2) if filename2 else ""
    second_is_image = data2 is not None and ext2 in _IMAGE_MIME
    extracted = ""
    if ext in _IMAGE_MIME:
        photos = [(data, _IMAGE_MIME[ext])]
        if second_is_image:
            photos.append((data2, _IMAGE_MIME[ext2]))  # type: ignore[arg-type]
        extracted = _describe_image(photos)
    elif ext == "pdf":
        extracted = _describe_pdf(data)
    elif ext == "docx":
        extracted = _describe_docx(data)
    elif ext in _SHEET_EXT or ext in _DECK_EXT:
        extracted = _describe_office(ext, data)
    elif ext in _VIDEO_EXT:
        extracted = _describe_video(data)
    elif ext in _TEXT_EXT:
        extracted = _read_text(data)
    elif ext in _NO_EXTRACTION:
        extracted = ""  # e.g. STL geometry — nothing to read, user's words carry it

    parts = [p for p in (user_description.strip(), extracted.strip()) if p]
    return "\n\n".join(parts) if parts else f"Dropped file: {filename} (no description given)"
