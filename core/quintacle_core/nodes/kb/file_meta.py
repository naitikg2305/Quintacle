"""Bake a file's own metadata into its note BODY so retrieval (and weak
local models) can answer from it — 2026-11-05.

A dropped PDF/DOCX/XLSX/PPTX/photo/video carries facts nobody typed: the
document's embedded title and author, when it was created, how many pages,
which camera took the photo, how long the clip runs. Those used to vanish at
drop. Every file save path now runs apply_file_meta(), which:

  1. re-reads each stored asset FROM DISK (never trusts client-sent
     metadata) and extracts deterministically — NO model call, stdlib +
     Pillow only (core/requirements.txt stays Termux/phone-safe):
       PDF        title, author, subject, creator, producer, created,
                  modified, pages (raw Info dict + compressed object
                  streams via zlib, XMP fallback)
       DOCX/XLSX/PPTX  title, subject, author (dc:creator),
                  last_modified_by, created, modified (docProps/core.xml)
                  + pages/slides/words from docProps/app.xml
       image      camera make/model, width×height, taken (EXIF; place is
                  photo_place's job)
       video/m4a  duration, created (mvhd / Apple creationdate), GPS
                  (©xyz / ISO6709) — tiny MP4/QuickTime box walker; WebM
                  and anything unparseable degrade to the common fields
       always     filename (original upload name), asset path, size, mime,
                  extension
  2. writes ONE visible line per asset just before the trailing
     `[asset](...)` lines (after any 📍 place line):

        🗂 PDF · "Austria itinerary" · 12 pages · created 2026-11-04 by Naitik · austria.pdf (128 KB) <!-- filemeta -->

     plus structured frontmatter `file_meta: [{...}, ...]` (one dict per
     asset; in store._INTERNAL_META so Browse doesn't list it as a field).
     The `<!-- filemeta -->` marker makes re-runs idempotent (replaced,
     never duplicated); retrieval.deterministic_prose_summary skips the line
     but it stays in the FTS body, so "who wrote the Austria itinerary"
     finds it.
  3. links the note to `journal:<created day>` with an `on_day` edge
     (source_of_edge "file_meta") when that journal day exists — the same
     rule photos follow — so day_bundle surfaces a boarding pass created on
     May 12 when asking about May 12. Re-synced: a stale file_meta day edge
     is removed.

Dates are normalized to ISO; timezone-aware ones are converted to Eastern
(clock.TIME_ZONE) so the linked day matches the owner's calendar."""
from __future__ import annotations

import io
import logging
import mimetypes
import re
import struct
import zipfile
import zlib
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

import frontmatter

from ... import clock
from .photo_place import _ASSET_LINE_RE, is_image_name

logger = logging.getLogger(__name__)

FILEMETA_MARKER = "<!-- filemeta -->"
FILEMETA_PREFIX = "🗂"
EDGE_SOURCE = "file_meta"

OOXML_EXTENSIONS = {"docx", "xlsx", "pptx", "docm", "xlsm", "pptm"}
MP4_EXTENSIONS = {"mp4", "mov", "m4v", "m4a", "3gp"}
VIDEO_EXTENSIONS = {"mp4", "mov", "m4v", "webm", "3gp", "mkv", "avi"}

# Don't hold a multi-GB video in memory twice just to read a header.
_MAX_PARSE_BYTES = 1024 * 1024 * 1024


def is_file_meta_line(line: str) -> bool:
    s = line.strip()
    return s.startswith(FILEMETA_PREFIX) and s.endswith(FILEMETA_MARKER)


def _ext(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


# --------------------------------------------------------------- dates


def _iso(dt: datetime | date | None) -> str | None:
    """ISO string; an aware datetime is converted to Eastern first."""
    if dt is None:
        return None
    if isinstance(dt, datetime):
        if dt.tzinfo is not None:
            dt = dt.astimezone(clock.TIME_ZONE)
        return dt.replace(microsecond=0).isoformat()
    return dt.isoformat()


_PDF_DATE_RE = re.compile(
    r"^(?:D:)?(\d{4})(\d{2})?(\d{2})?(\d{2})?(\d{2})?(\d{2})?\s*(?:([Zz+\-])\s*(\d{2})?'?\s*(\d{2})?'?)?"
)


def parse_pdf_date(raw: str | None) -> str | None:
    """`D:YYYYMMDDHHmmSSOHH'mm'` (every part after the year optional) → ISO.
    None for anything that doesn't parse."""
    if not raw:
        return None
    m = _PDF_DATE_RE.match(raw.strip())
    if not m:
        return None
    y, mo, d, h, mi, s, sign, tzh, tzm = m.groups()
    try:
        dt = datetime(int(y), int(mo or 1), int(d or 1), int(h or 0), int(mi or 0), int(s or 0))
    except ValueError:
        return None
    if sign in ("Z", "z"):
        dt = dt.replace(tzinfo=timezone.utc)
    elif sign in ("+", "-"):
        off = timedelta(hours=int(tzh or 0), minutes=int(tzm or 0))
        dt = dt.replace(tzinfo=timezone(off if sign == "+" else -off))
    return _iso(dt)


def parse_iso_date(raw: str | None) -> str | None:
    """W3CDTF / ISO 8601 (`2026-11-04T10:00:00Z`, `2026-11-04`, ±hh:mm or
    ±hhmm offsets) → normalized ISO; None when unparseable."""
    if not raw:
        return None
    s = raw.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    s = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", s)
    try:
        return _iso(datetime.fromisoformat(s))
    except ValueError:
        try:
            return _iso(date.fromisoformat(s[:10]))
        except ValueError:
            return None


def _day_of(iso: str | None) -> str | None:
    if not iso:
        return None
    try:
        d = date.fromisoformat(iso[:10])
    except ValueError:
        return None
    return d.isoformat() if 1971 <= d.year <= 2200 else None


# --------------------------------------------------------------- PDF


def _pdf_literal(buf: bytes, i: int) -> tuple[bytes, int]:
    """Parse a PDF literal string starting at buf[i] == '('. Returns (raw
    bytes, index after the closing paren)."""
    out = bytearray()
    depth = 0
    i += 1
    n = len(buf)
    while i < n:
        c = buf[i]
        if c == 0x5C:  # backslash
            i += 1
            if i >= n:
                break
            e = buf[i]
            esc = {0x6E: 10, 0x72: 13, 0x74: 9, 0x62: 8, 0x66: 12, 0x28: 0x28, 0x29: 0x29, 0x5C: 0x5C}
            if e in esc:
                out.append(esc[e])
                i += 1
            elif 0x30 <= e <= 0x37:
                j = i
                while j < n and j < i + 3 and 0x30 <= buf[j] <= 0x37:
                    j += 1
                out.append(int(buf[i:j], 8) & 0xFF)
                i = j
            elif e in (10, 13):  # line continuation
                i += 1
                if e == 13 and i < n and buf[i] == 10:
                    i += 1
            else:
                out.append(e)
                i += 1
            continue
        if c == 0x28:
            depth += 1
        elif c == 0x29:
            if depth == 0:
                return bytes(out), i + 1
            depth -= 1
        out.append(c)
        i += 1
    return bytes(out), i


def _pdf_text(raw: bytes) -> str:
    if raw.startswith(b"\xfe\xff"):
        return raw[2:].decode("utf-16-be", errors="replace")
    if raw.startswith(b"\xff\xfe"):
        return raw[2:].decode("utf-16-le", errors="replace")
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8", errors="replace")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def _pdf_value_at(buf: bytes, i: int, resolve) -> str | None:
    n = len(buf)
    while i < n and buf[i] in b" \t\r\n\f\x00":
        i += 1
    if i >= n:
        return None
    if buf[i] == 0x28:
        raw, _ = _pdf_literal(buf, i)
        return _pdf_text(raw).strip("\x00").strip()
    if buf[i] == 0x3C and buf[i + 1 : i + 2] != b"<":
        j = buf.find(b">", i)
        if j < 0:
            return None
        hexs = re.sub(rb"\s", b"", buf[i + 1 : j])
        if len(hexs) % 2:
            hexs += b"0"
        try:
            return _pdf_text(bytes.fromhex(hexs.decode("ascii"))).strip("\x00").strip()
        except ValueError:
            return None
    m = re.match(rb"(\d+)\s+(\d+)\s+R", buf[i : i + 40])
    if m and resolve is not None:
        body = resolve(int(m.group(1)))
        if body is not None:
            return _pdf_value_at(body, 0, None)
    return None


class _PdfObjects:
    """Lazy object lookup over the raw file + every FlateDecode object stream."""

    def __init__(self, data: bytes):
        self.data = data
        self._objstm: dict[int, bytes] | None = None
        self.inflated: list[bytes] = []

    def _load_objstm(self) -> dict[int, bytes]:
        if self._objstm is not None:
            return self._objstm
        objs: dict[int, bytes] = {}
        for m in re.finditer(rb"/Type\s*/ObjStm", self.data):
            start = self.data.rfind(b"<<", 0, m.start())
            s = self.data.find(b"stream", m.end())
            if start < 0 or s < 0:
                continue
            head = self.data[start:s]
            s += 6
            if self.data[s : s + 2] == b"\r\n":
                s += 2
            elif self.data[s : s + 1] in (b"\n", b"\r"):
                s += 1
            e = self.data.find(b"endstream", s)
            if e < 0:
                continue
            try:
                content = zlib.decompress(self.data[s:e])
            except zlib.error:
                try:
                    content = zlib.decompressobj().decompress(self.data[s:e])
                except zlib.error:
                    continue
            self.inflated.append(content)
            nm = re.search(rb"/N\s+(\d+)", head)
            fm = re.search(rb"/First\s+(\d+)", head)
            if not nm or not fm:
                continue
            first = int(fm.group(1))
            nums = [int(x) for x in content[:first].split()]
            pairs = list(zip(nums[0::2], nums[1::2]))[: int(nm.group(1))]
            for k, (num, off) in enumerate(pairs):
                end = first + pairs[k + 1][1] if k + 1 < len(pairs) else len(content)
                objs[num] = content[first + off : end]
        self._objstm = objs
        return objs

    def get(self, num: int) -> bytes | None:
        hits = list(re.finditer(rb"(?<![\d])%d\s+\d+\s+obj\b" % num, self.data))
        if hits:
            start = hits[-1].end()
            end = self.data.find(b"endobj", start)
            return self.data[start : end if end > 0 else start + 65536]
        return self._load_objstm().get(num)


def _pdf_meta(data: bytes) -> dict:
    out: dict = {}
    objs = _PdfObjects(data)
    info_refs = re.findall(rb"/Info\s+(\d+)\s+\d+\s+R", data)
    info = objs.get(int(info_refs[-1])) if info_refs else None
    if info is None:
        objs._load_objstm()
        # No trailer ref (or a broken one) — any dict carrying the usual keys.
        for blob in [data, *objs.inflated]:
            m = None
            for m in re.finditer(rb"/(?:Producer|CreationDate|Author|Title)\s*[(<]", blob):
                pass
            if m is not None:
                info = blob[max(0, blob.rfind(b"<<", 0, m.start())) :]
                break
    if info is not None:
        for key, name in (
            ("title", b"Title"),
            ("author", b"Author"),
            ("subject", b"Subject"),
            ("creator", b"Creator"),
            ("producer", b"Producer"),
            ("created", b"CreationDate"),
            ("modified", b"ModDate"),
        ):
            m = re.search(rb"/" + name + rb"(?![A-Za-z])", info)
            if not m:
                continue
            val = _pdf_value_at(info, m.end(), objs.get)
            if not val:
                continue
            if key in ("created", "modified"):
                val = parse_pdf_date(val)
            if val:
                out[key] = val[:300]
    # XMP fallback (often uncompressed): fills only what Info lacked.
    xmp_pairs = (
        ("title", rb"<dc:title>\s*<rdf:Alt>\s*<rdf:li[^>]*>(.*?)</rdf:li>"),
        ("author", rb"<dc:creator>\s*<rdf:Seq>\s*<rdf:li[^>]*>(.*?)</rdf:li>"),
        ("created", rb"<xmp:CreateDate>(.*?)</xmp:CreateDate>"),
        ("modified", rb"<xmp:ModifyDate>(.*?)</xmp:ModifyDate>"),
    )
    for key, pat in xmp_pairs:
        if key in out:
            continue
        m = re.search(pat, data, re.S)
        if m:
            val = m.group(1).decode("utf-8", errors="replace").strip()
            if key in ("created", "modified"):
                val = parse_iso_date(val)
            if val:
                out[key] = val[:300]
    # Page count: the largest /Count on a /Type /Pages dict (the root).
    counts: list[int] = []
    for blob in [data, *objs.inflated]:
        for m in re.finditer(rb"/Type\s*/Pages\b", blob):
            lo = blob.rfind(b"<<", 0, m.start())
            hi = blob.find(b">>", m.end())
            seg = blob[lo if lo >= 0 else m.start() : hi if hi > 0 else m.end() + 200]
            c = re.search(rb"/Count\s+(\d+)", seg)
            if c:
                counts.append(int(c.group(1)))
    if counts:
        out["pages"] = max(counts)
    else:
        n = sum(len(re.findall(rb"/Type\s*/Page(?![s\w])", b)) for b in [data, *objs.inflated])
        if n:
            out["pages"] = n
    return out


# --------------------------------------------------------------- OOXML

_NS = {
    "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
    "dc": "http://purl.org/dc/elements/1.1/",
    "dcterms": "http://purl.org/dc/terms/",
    "ep": "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties",
}


def _ooxml_meta(data: bytes) -> dict:
    out: dict = {}
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = set(z.namelist())
        if "docProps/core.xml" in names:
            root = ET.fromstring(z.read("docProps/core.xml"))
            for key, path in (
                ("title", "dc:title"),
                ("subject", "dc:subject"),
                ("author", "dc:creator"),
                ("last_modified_by", "cp:lastModifiedBy"),
                ("created", "dcterms:created"),
                ("modified", "dcterms:modified"),
            ):
                el = root.find(path, _NS)
                if el is None or not (el.text or "").strip():
                    continue
                val = el.text.strip()
                if key in ("created", "modified"):
                    val = parse_iso_date(val)
                if val:
                    out[key] = val[:300]
        if "docProps/app.xml" in names:
            root = ET.fromstring(z.read("docProps/app.xml"))
            for key, tag in (("pages", "Pages"), ("slides", "Slides"), ("words", "Words")):
                el = root.find(f"ep:{tag}", _NS)
                if el is not None and (el.text or "").strip().isdigit() and int(el.text) > 0:
                    out[key] = int(el.text)
        sheets = [n for n in names if re.match(r"xl/worksheets/sheet\d+\.xml$", n)]
        if sheets:
            out["sheets"] = len(sheets)
    return out


# --------------------------------------------------------------- images


def _image_meta(data: bytes) -> dict:
    from PIL import Image

    from .drop import extract_photo_date, extract_photo_datetime

    out: dict = {}
    img = Image.open(io.BytesIO(data))
    out["width"], out["height"] = img.size
    try:
        exif = img.getexif()
        make = str(exif.get(271) or "").strip().strip("\x00")
        model = str(exif.get(272) or "").strip().strip("\x00")
        if make:
            out["camera_make"] = make[:80]
        if model:
            out["camera_model"] = model[:80]
    except Exception:
        pass
    taken = extract_photo_datetime(data) or extract_photo_date(data)
    if taken is not None:
        out["taken"] = _iso(taken)
    return out


# --------------------------------------------------------------- MP4 / QuickTime

_MP4_EPOCH = datetime(1904, 1, 1, tzinfo=timezone.utc)
_CONTAINERS = {b"moov", b"udta", b"trak", b"mdia", b"meta"}


def _boxes(buf: bytes, start: int, end: int):
    i = start
    while i + 8 <= end:
        size, typ = struct.unpack(">I4s", buf[i : i + 8])
        hdr = 8
        if size == 1:
            if i + 16 > end:
                return
            size = struct.unpack(">Q", buf[i + 8 : i + 16])[0]
            hdr = 16
        elif size == 0:
            size = end - i
        if size < hdr:
            return
        yield typ, i + hdr, min(i + size, end)
        i += size


def _find_box(buf: bytes, start: int, end: int, path: list[bytes]):
    for typ, s, e in _boxes(buf, start, end):
        if typ == path[0]:
            if len(path) == 1:
                return s, e
            if typ == b"meta":
                s += 4  # full box: version + flags
            return _find_box(buf, s, e, path[1:])
    return None


_ISO6709_RE = re.compile(rb"([+-]\d{1,2}(?:\.\d+)?)([+-]\d{1,3}(?:\.\d+)?)")
_APPLE_DATE_RE = re.compile(rb"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:?\d{2})?)")


def _mp4_meta(data: bytes) -> dict:
    out: dict = {}
    moov = _find_box(data, 0, len(data), [b"moov"])
    if moov is None:
        return out
    ms, me = moov
    mvhd = _find_box(data, ms, me, [b"mvhd"])
    if mvhd is not None:
        s, _ = mvhd
        version = data[s]
        if version == 1:
            created, _mod, timescale, duration = struct.unpack(">QQIQ", data[s + 4 : s + 32])
        else:
            created, _mod, timescale, duration = struct.unpack(">IIII", data[s + 4 : s + 20])
        if timescale:
            out["duration_s"] = round(duration / timescale, 2)
        if created:
            dt = _MP4_EPOCH + timedelta(seconds=created)
            if dt.year >= 1971:
                out["created"] = _iso(dt)
    moov_bytes = data[ms:me]
    # Apple's own creationdate key (local wall time + offset) beats mvhd's UTC.
    k = moov_bytes.find(b"com.apple.quicktime.creationdate")
    if k >= 0:
        # ilst values come after the keys box — scan forward for the first ISO stamp.
        m = _APPLE_DATE_RE.search(moov_bytes, k)
        if m:
            iso = parse_iso_date(m.group(1).decode())
            if iso:
                out["created"] = iso
    loc = None
    xyz = _find_box(data, ms, me, [b"udta", b"\xa9xyz"])
    if xyz is not None:
        loc = _ISO6709_RE.search(data[xyz[0] + 4 : xyz[1]])
    if loc is None:
        k = moov_bytes.find(b"location.ISO6709")
        if k >= 0:
            loc = _ISO6709_RE.search(moov_bytes, k + 16)
    if loc is not None:
        try:
            lat, lon = float(loc.group(1)), float(loc.group(2))
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                out["location"] = {"lat": round(lat, 6), "lon": round(lon, 6)}
        except ValueError:
            pass
    return out


# --------------------------------------------------------------- extraction


def extract_file_meta(filename: str, data: bytes, *, asset: str | None = None) -> dict:
    """Deterministic metadata for one file. Never raises — a parser failure
    leaves just the common fields (filename, size, mime, ext)."""
    ext = _ext(filename)
    meta: dict = {"filename": filename, "ext": ext, "size": len(data)}
    if asset:
        meta["asset"] = asset
    mime = mimetypes.guess_type(filename)[0]
    if mime:
        meta["mime"] = mime
    if len(data) > _MAX_PARSE_BYTES:
        return meta
    try:
        if ext == "pdf" or data[:5] == b"%PDF-":
            meta["kind"] = "pdf"
            meta.update(_pdf_meta(data))
        elif ext in OOXML_EXTENSIONS:
            meta["kind"] = {"x": "spreadsheet", "p": "presentation"}.get(ext[0], "document")
            meta.update(_ooxml_meta(data))
        elif is_image_name(filename):
            meta["kind"] = "image"
            meta.update(_image_meta(data))
        elif ext in MP4_EXTENSIONS or ext in VIDEO_EXTENSIONS:
            meta["kind"] = "audio" if ext == "m4a" else "video"
            if ext in MP4_EXTENSIONS:
                meta.update(_mp4_meta(data))
    except Exception as exc:
        logger.info("file meta extraction failed for %s: %s", filename, exc)
    day = _day_of(meta.get("taken") or meta.get("created"))
    if day:
        meta["day"] = day
    return meta


# --------------------------------------------------------------- the line


def _human_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    for unit in ("KB", "MB", "GB"):
        n /= 1024
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if n >= 10 else f"{n:.1f} {unit}"
    return f"{n} B"


def _duration(s: float) -> str:
    total = int(round(s))
    h, rem = divmod(total, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def compose_file_meta_line(meta: dict) -> str:
    parts: list[str] = [(meta.get("ext") or "file").upper()]
    if meta.get("title"):
        parts.append(f'"{meta["title"]}"')
    if meta.get("subject") and meta.get("subject") != meta.get("title"):
        parts.append(f"subject: {meta['subject']}")
    for key, word in (("pages", "page"), ("slides", "slide"), ("sheets", "sheet")):
        if meta.get(key):
            parts.append(_plural(int(meta[key]), word))
    camera = " ".join(v for v in (meta.get("camera_make"), meta.get("camera_model")) if v)
    if camera:
        parts.append(camera)
    if meta.get("width") and meta.get("height"):
        parts.append(f"{meta['width']}×{meta['height']}")
    if meta.get("duration_s"):
        parts.append(_duration(float(meta["duration_s"])))
    if meta.get("taken"):
        parts.append(f"taken {meta['taken'][:16].replace('T', ' ')}")
    if meta.get("created"):
        by = f" by {meta['author']}" if meta.get("author") else ""
        parts.append(f"created {meta['created'][:10]}{by}")
    elif meta.get("author"):
        parts.append(f"by {meta['author']}")
    if meta.get("modified") and meta.get("modified", "")[:10] != (meta.get("created") or "")[:10]:
        by = f" by {meta['last_modified_by']}" if meta.get("last_modified_by") else ""
        parts.append(f"modified {meta['modified'][:10]}{by}")
    loc = meta.get("location")
    if isinstance(loc, dict) and loc.get("lat") is not None:
        parts.append(f"{float(loc['lat']):.4f}, {float(loc['lon']):.4f}")
    parts.append(f"{meta.get('filename') or 'file'} ({_human_size(int(meta.get('size') or 0))})")
    text = " · ".join(str(p).replace("\n", " ") for p in parts)
    return f"{FILEMETA_PREFIX} {text} {FILEMETA_MARKER}"


def insert_file_meta_lines(body: str, lines: list[str]) -> str:
    """Remove any existing 🗂 lines, then put `lines` just before the
    trailing `[asset](...)` block (so after a 📍 place line). Idempotent."""
    trailing_nl = body.endswith("\n")
    rows = [l for l in body.rstrip("\n").split("\n") if not is_file_meta_line(l)]
    i = len(rows)
    while i > 0 and (_ASSET_LINE_RE.match(rows[i - 1].strip()) or not rows[i - 1].strip()):
        i -= 1
    head, tail = rows[:i], [l for l in rows[i:] if l.strip()]
    while head and not head[-1].strip():
        head.pop()
    out = list(head)
    if lines:
        if out:
            out.append("")
        out.extend(lines)
    if tail:
        if out:
            out.append("")
        out.extend(tail)
    text = "\n".join(out)
    return text + "\n" if trailing_nl else text


# --------------------------------------------------------------- save hook


@dataclass
class FileMetaResult:
    note_id: str
    metas: list[dict] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)
    body: str = ""
    changed: bool = False
    days: list[str] = field(default_factory=list)
    new_edge_ids: list[str] = field(default_factory=list)

    def apply_to(self, body: str) -> str:
        """The same 🗂 lines placed into another copy of the body (the
        caller's in-memory content it is about to index)."""
        return insert_file_meta_lines(body, self.lines)


def _asset_paths(content: str) -> list[str]:
    return [m.group(1) for line in content.splitlines() if (m := _ASSET_LINE_RE.match(line.strip()))]


def _journal_exists(journal_store, day: str) -> bool:
    try:
        return journal_store.load(date.fromisoformat(day)) is not None
    except Exception:
        return False


def link_file_days(note_id: str, days: list[str], journal_store) -> list[str]:
    """Sync this note's `on_day` file_meta edges to `days` (only days whose
    journal exists). Returns ids of edges newly created. Never raises."""
    try:
        from ...graph import get_graph_store

        gs = get_graph_store()
    except Exception:
        return []
    try:
        wanted = {f"journal:{d}" for d in days if journal_store is not None and _journal_exists(journal_store, d)}
        current = gs.conn.execute(
            "SELECT id, target_id FROM edges WHERE source_id = ? AND source_of_edge = ? AND kind = 'on_day'",
            (note_id, EDGE_SOURCE),
        ).fetchall()
        for row in current:
            if row["target_id"] not in wanted:
                gs.remove_edge(row["id"])
        created = []
        for target in sorted(wanted):
            if gs._existing_edge_id(note_id, target, "on_day") is None:
                created.append(gs.create_edge(note_id, target, "on_day", EDGE_SOURCE)["id"])
        return created
    except Exception as exc:
        logger.warning("file_meta day link failed for %s: %s", note_id, exc)
        return []


def apply_file_meta(
    store,
    folder: str,
    slug: str,
    names: dict[str, str] | None = None,
    *,
    journal_store=None,
    dry_run: bool = False,
) -> FileMetaResult | None:
    """THE save hook. Re-reads every `[asset](...)` file of the note from
    disk, extracts metadata, writes the 🗂 lines + `file_meta` frontmatter,
    and (unless dry_run) syncs the on_day journal edges. `names` maps asset
    path → original upload filename (falls back to the name already in
    frontmatter, then the stored basename). None when the note has no
    assets. Never raises; does not restamp `edited`."""
    try:
        path = store.entry_path(folder, slug)
        if not path.is_file():
            return None
        post = frontmatter.loads(path.read_text(encoding="utf-8"))
        assets = _asset_paths(post.content)
        if not assets:
            return None
        folder_slug = str(path.parent.relative_to(store.root)).replace("\\", "/")
        note_id = f"note:{folder_slug}/{path.stem}"
        previous = post.metadata.get("file_meta")
        prev_names = {
            m.get("asset"): m.get("filename") for m in (previous if isinstance(previous, list) else []) if isinstance(m, dict)
        }
        names = names or {}
        metas = []
        for asset in assets:
            data = store.read_asset(folder, asset)
            if data is None:
                continue
            name = names.get(asset) or prev_names.get(asset) or asset.rsplit("/", 1)[-1]
            metas.append(extract_file_meta(name, data, asset=asset))
        if not metas:
            return None
        lines = [compose_file_meta_line(m) for m in metas]
        new_body = insert_file_meta_lines(post.content, lines)
        days = sorted({m["day"] for m in metas if m.get("day")})
        result = FileMetaResult(
            note_id=note_id,
            metas=metas,
            lines=lines,
            body=new_body,
            changed=new_body != post.content or previous != metas,
            days=days,
        )
        if dry_run:
            return result
        if result.changed:
            post.content = new_body
            post["file_meta"] = metas
            path.write_text(frontmatter.dumps(post), encoding="utf-8")
        result.new_edge_ids = link_file_days(note_id, days, journal_store)
        return result
    except Exception as exc:
        logger.warning("apply_file_meta failed for %s/%s: %s", folder, slug, exc)
        return None


def proposal_file_meta(files: list[tuple[str, bytes]]) -> list[dict]:
    """Drop-step preview: the same extraction over the uploaded bytes, for
    the review card's read-only "File info" line. Display only — Save
    re-extracts from the stored file."""
    out = []
    for name, data in files:
        if data is None:
            continue
        meta = extract_file_meta(name or "upload", data)
        meta["line"] = compose_file_meta_line(meta).removesuffix(FILEMETA_MARKER).strip()
        out.append(meta)
    return out


def backfill_file_meta(store, *, dry_run: bool = True, index=None, journal_store=None) -> list[dict]:
    """Walk every KB note with asset lines, add/refresh its 🗂 lines +
    `file_meta`, sync on_day edges and (when applying) re-index via
    `index(folder, slug, title, body)`. One row per note that would
    change / changed."""
    results = []
    for folder in store.list_folders():
        for slug in store.list_entries(folder):
            info = apply_file_meta(store, folder, slug, journal_store=journal_store, dry_run=dry_run)
            if info is None:
                continue
            if not info.changed and not info.new_edge_ids:
                continue
            row = {"folder": folder, "slug": slug, "lines": info.lines, "days": info.days, "new_edges": len(info.new_edge_ids)}
            if not dry_run and index is not None:
                full = store.read_full(folder, slug) or {}
                index(folder, slug, full.get("title") or slug, info.body)
            results.append(row)
    return results
