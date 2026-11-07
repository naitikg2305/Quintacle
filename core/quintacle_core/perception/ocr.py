"""Local OCR — the first stage of the local-first image pipeline (2026-11-06).

The owner's call: "it should always have been local ... YOLO plus OCR". Most
of the photos Quintacle is asked to understand (nutrition labels, receipts,
IDs/leases, product bottles) are TEXT. Reading that text on-device and then
parsing it in code (nodes/logs/label_parser.py, nodes/finance/receipt_parser.py)
is cheaper, faster and more exact than shipping the picture to a cloud VLM —
deterministic core, models at the edges.

Backends, picked per call by QUINTACLE_OCR_BACKEND (default auto):

  rapidocr    RapidOCR 3.x (`pip install rapidocr onnxruntime`): PaddleOCR's
              PP-OCR det/cls/rec models exported to ONNX, run on onnxruntime
              CPU. The wheel BUNDLES its models (~32 MB: det 9.9 MB, rec
              21 MB, cls 0.6 MB) — no download at first use. The legacy
              `rapidocr_onnxruntime` 1.x package is accepted too.
  tesseract   the `tesseract` CLI (Arch/Debian package, Termux `pkg install
              tesseract`). No Python binding needed — we shell out with TSV
              output. The phone-friendliest option: a single native pkg.
  auto        rapidocr if importable, else tesseract if on PATH, else none.
  off         never OCR (the test suite sets this, so a dev machine's
              tesseract is never exercised by tests).

ocr_image() returns None when no backend is available — callers treat that
as "this image can't be read locally" (image_policy decides what happens
next). Nothing here imports a heavy dependency at module load: core stays
phone/Termux-safe and the suite passes without any OCR installed. Deps:
core/requirements-ocr.txt.

Output is ROW-GROUPED: both engines return text fragments (RapidOCR splits
"Total Fat 8g" and "10%" into two boxes on the same row); group_rows() merges
fragments whose vertical extents overlap into one line, left-to-right, so the
parsers see "Total Fat 8g 10%" the way a person reads the panel.

2026-11-07 deskew: a hand-held phone photo is rarely level. On the owner's
Toast receipt the page sat ~9 degrees off, so the price column (right) ran
~85 px lower than its labels (left) and the axis-aligned boxes of tilted
text were twice their real height — row grouping chained the whole receipt
into a few giant rows and the parser read the total as $19.00 (real
$510.13). RapidOCR returns each fragment's quadrilateral; its top-edge
angle and true width/height are kept, the page's dominant angle (median of
the wide fragments) is undone in code, and rows are grouped by deskewed
CENTER distance (not union-box overlap, which let one tall/tilted fragment
glue neighbouring rows together). OcrResult.fragments carries the
deskewed per-fragment boxes so parsers can pair labels with values
themselves (receipt_parser does).
"""

from __future__ import annotations

import csv
import hashlib
import io
import logging
import os
import shutil
import subprocess
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import NamedTuple

logger = logging.getLogger(__name__)

OCR_BACKEND_ENV = "QUINTACLE_OCR_BACKEND"
VALID_BACKENDS = ("auto", "rapidocr", "tesseract", "off")

# Phone photos are 12-50 MP; OCR accuracy plateaus far below that and both
# engines get slow. Long side capped here before any engine sees the image.
_MAX_SIDE = 2000
_TESSERACT_TIMEOUT = 60


class OcrLine(NamedTuple):
    text: str
    box: tuple[float, float, float, float]  # x, y, w, h — DESKEWED pixels of the (possibly downscaled) image
    conf: float  # 0-1
    angle: float = 0.0  # this fragment's own text angle (degrees) minus the page's dominant angle
    clipped: bool = False  # the fragment touches the image border — text cut off by the frame


@dataclass
class OcrResult:
    lines: list[OcrLine]
    text: str  # lines joined with "\n", top to bottom
    engine: str  # "rapidocr" | "tesseract"
    image_size: tuple[int, int] = (0, 0)
    extra: dict = field(default_factory=dict)
    # 2026-11-07: individual (un-merged) fragments, deskewed like `lines`.
    # Empty for results built by hand (tests) — callers fall back to lines.
    fragments: list[OcrLine] = field(default_factory=list)

    @property
    def word_count(self) -> int:
        return len(self.text.split())


def _rapidocr_flavor() -> str | None:
    """'v3' for the current `rapidocr` package, 'v1' for the legacy
    `rapidocr_onnxruntime`, None when neither imports."""
    try:
        import rapidocr  # noqa: F401

        return "v3"
    except Exception:
        pass
    try:
        import rapidocr_onnxruntime  # noqa: F401

        return "v1"
    except Exception:
        return None


def ocr_backend() -> str | None:
    """Which engine ocr_image() would use right now, or None (none
    installed / OCR switched off)."""
    mode = (os.environ.get(OCR_BACKEND_ENV) or "auto").strip().lower()
    if mode == "off":
        return None
    if mode in ("auto", "rapidocr") and _rapidocr_flavor() is not None:
        return "rapidocr"
    if mode in ("auto", "tesseract") and shutil.which("tesseract"):
        return "tesseract"
    return None


def ocr_available() -> bool:
    return ocr_backend() is not None


# --------------------------------------------------------------- row grouping


class _Frag(NamedTuple):
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    conf: float
    angle: float = 0.0  # degrees, text baseline vs horizontal (image y-down: + = slopes down to the right)
    tw: float = 0.0  # true (rotated) text width / height from the quad; 0 = use the axis-aligned box
    th: float = 0.0


def _median(values: list[float]) -> float:
    vals = sorted(values)
    n = len(vals)
    return 0.0 if not n else (vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2)


def page_angle(frags: list[_Frag]) -> float:
    """The page's dominant text angle (degrees): median over the WIDE
    fragments (a 2-letter box's angle is noise); 0 under half a degree."""
    wide = [f.angle for f in frags if (f.tw or (f.x1 - f.x0)) >= 2.5 * max(f.th or (f.y1 - f.y0), 1.0)]
    angle = _median(wide if len(wide) >= 3 else [f.angle for f in frags])
    return angle if abs(angle) >= 0.5 else 0.0


def deskew(frags: list[_Frag] | list[tuple], image_size: tuple[int, int] | None = None) -> list[OcrLine]:
    """Per-fragment boxes in a frame rotated so the page's text runs level.
    Pure function. Without quad info (tesseract, hand-built tuples) the
    angle is 0 and the boxes come back unchanged. With `image_size`, a
    fragment whose ORIGINAL box touches the frame is marked clipped."""
    import math

    items = [f if isinstance(f, _Frag) else _Frag(*f) for f in frags if str(f[0]).strip()]
    theta = page_angle(items) if items else 0.0
    rad = math.radians(theta)
    cos, sin = math.cos(rad), math.sin(rad)
    out: list[OcrLine] = []
    for f in items:
        cx, cy = (f.x0 + f.x1) / 2, (f.y0 + f.y1) / 2
        w = f.tw or (f.x1 - f.x0)
        h = f.th or (f.y1 - f.y0)
        if theta:
            cx, cy = cx * cos + cy * sin, -cx * sin + cy * cos
        clipped = bool(image_size) and (
            f.x0 <= 2 or f.y0 <= 2 or f.x1 >= image_size[0] - 3 or f.y1 >= image_size[1] - 3
        )
        out.append(OcrLine(f.text, (cx - w / 2, cy - h / 2, w, h), round(float(f.conf), 4), round(f.angle - theta, 2), clipped))
    return out


def group_rows(frags: list[_Frag] | list[tuple]) -> list[OcrLine]:
    """Merge fragments sitting on the same visual row into one line, after
    deskewing (see deskew()). A fragment joins a row when its center is
    within half the smaller of (its height, the row's median height) of
    the row's mean center — center distance, so one tall or tilted box
    can't chain neighbouring rows together. Pure function — unit-tested
    without any engine."""
    items = deskew(frags)
    items.sort(key=lambda f: (f.box[1] + f.box[3] / 2, f.box[0]))
    rows: list[list[OcrLine]] = []
    for frag in items:
        h = max(frag.box[3], 1.0)
        cy = frag.box[1] + h / 2
        best, best_d = None, None
        for row in rows[-4:]:  # only recent rows can be near (sorted by center y)
            rcy = sum(r.box[1] + r.box[3] / 2 for r in row) / len(row)
            rh = _median([max(r.box[3], 1.0) for r in row])
            d = abs(cy - rcy)
            if d <= 0.5 * min(h, rh) and (best_d is None or d < best_d):
                best, best_d = row, d
        if best is not None:
            best.append(frag)
        else:
            rows.append([frag])
    lines: list[OcrLine] = []
    for row in rows:
        row.sort(key=lambda f: f.box[0])
        x0 = min(f.box[0] for f in row)
        y0 = min(f.box[1] for f in row)
        x1 = max(f.box[0] + f.box[2] for f in row)
        y1 = max(f.box[1] + f.box[3] for f in row)
        text = " ".join(f.text.strip() for f in row)
        lines.append(OcrLine(text, (x0, y0, x1 - x0, y1 - y0), round(min(f.conf for f in row), 4)))
    lines.sort(key=lambda ln: ln.box[1] + ln.box[3] / 2)
    return lines


# ------------------------------------------------------------------ engines


_rapid_engine = None


def _get_rapid():
    global _rapid_engine
    if _rapid_engine is None:
        if _rapidocr_flavor() == "v3":
            from rapidocr import RapidOCR
        else:
            from rapidocr_onnxruntime import RapidOCR
        _rapid_engine = RapidOCR()
        # RapidOCR logs every model load at INFO through its own logger.
        logging.getLogger("RapidOCR").setLevel(logging.WARNING)
    return _rapid_engine


def _quad_frag(box, text, score) -> _Frag:
    """RapidOCR quad (TL, TR, BR, BL) -> fragment with its axis-aligned
    extent plus the text's own angle and true width/height."""
    import math

    pts = [(float(p[0]), float(p[1])) for p in box]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    if len(pts) == 4:
        (ax, ay), (bx, by), _c, (dx, dy) = pts
        angle = math.degrees(math.atan2(by - ay, bx - ax))
        tw, th = math.hypot(bx - ax, by - ay), math.hypot(dx - ax, dy - ay)
        if abs(angle) > 45:  # vertical / upside-down text: no usable baseline
            angle, tw, th = 0.0, 0.0, 0.0
    else:
        angle, tw, th = 0.0, 0.0, 0.0
    return _Frag(str(text), min(xs), min(ys), max(xs), max(ys), float(score), angle, tw, th)


def _run_rapidocr(png: bytes) -> list[_Frag]:
    engine = _get_rapid()
    out = engine(png)
    frags: list[_Frag] = []
    if hasattr(out, "txts"):  # rapidocr 3.x: RapidOCROutput
        boxes = out.boxes if out.boxes is not None else []
        for box, text, score in zip(boxes, out.txts or (), out.scores or ()):
            frags.append(_quad_frag(box, text, score))
    else:  # rapidocr_onnxruntime 1.x: (result, elapse), result = [[box, text, score], ...] | None
        result = out[0] if isinstance(out, tuple) else out
        for box, text, score in result or []:
            frags.append(_quad_frag(box, text, score))
    return frags


def _run_tesseract(png: bytes) -> list[_Frag]:
    """`tesseract stdin stdout --psm 4 tsv` — psm 4 = one column of text of
    variable sizes, the shape of a label panel or a receipt. Words grouped
    by tesseract's own (block, par, line) ids, then row-grouped like
    RapidOCR's fragments."""
    proc = subprocess.run(
        ["tesseract", "stdin", "stdout", "--psm", "4", "tsv"],
        input=png,
        capture_output=True,
        timeout=_TESSERACT_TIMEOUT,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"tesseract failed: {proc.stderr.decode(errors='replace')[:200]}")
    reader = csv.DictReader(io.StringIO(proc.stdout.decode("utf-8", errors="replace")), delimiter="\t", quoting=csv.QUOTE_NONE)
    words: "OrderedDict[tuple, list[dict]]" = OrderedDict()
    for row in reader:
        text = (row.get("text") or "").strip()
        try:
            conf = float(row.get("conf") or -1)
        except ValueError:
            conf = -1
        if not text or conf < 0:
            continue
        key = (row.get("block_num"), row.get("par_num"), row.get("line_num"))
        words.setdefault(key, []).append({**row, "conf": conf, "text": text})
    frags: list[_Frag] = []
    for ws in words.values():
        x0 = min(int(w["left"]) for w in ws)
        y0 = min(int(w["top"]) for w in ws)
        x1 = max(int(w["left"]) + int(w["width"]) for w in ws)
        y1 = max(int(w["top"]) + int(w["height"]) for w in ws)
        conf = sum(w["conf"] for w in ws) / len(ws) / 100.0
        frags.append(_Frag(" ".join(w["text"] for w in ws), x0, y0, x1, y1, conf))
    return frags


def _prepare(data: bytes) -> tuple[bytes, tuple[int, int]]:
    """Decode, upright by EXIF orientation, downscale, re-encode as PNG —
    both engines read PNG, and tesseract can't read every format PIL can."""
    from PIL import Image, ImageOps

    img = Image.open(io.BytesIO(data))
    img.load()
    img = ImageOps.exif_transpose(img).convert("RGB")
    if max(img.size) > _MAX_SIDE:
        scale = _MAX_SIDE / max(img.size)
        img = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue(), img.size


# One request reads the same photo several times (classify, then the label
# parse, then the kb description) — OCR once per content hash.
_CACHE: "OrderedDict[str, OcrResult | None]" = OrderedDict()
_CACHE_SIZE = 16


def clear_cache() -> None:
    _CACHE.clear()


def ocr_image(data: bytes) -> OcrResult | None:
    """Read the text in one photo. None = no OCR backend available (or the
    engine failed — logged). Raises ValueError for bytes PIL can't decode."""
    backend = ocr_backend()
    if backend is None:
        return None
    key = f"{backend}:{hashlib.sha256(data).hexdigest()}"
    if key in _CACHE:
        _CACHE.move_to_end(key)
        return _CACHE[key]
    try:
        png, size = _prepare(data)
    except Exception as exc:
        raise ValueError("not a decodable image") from exc
    try:
        frags = _run_rapidocr(png) if backend == "rapidocr" else _run_tesseract(png)
    except Exception as exc:
        # e.g. tesseract installed without its English data
        # (Arch: `pacman -S tesseract-data-eng`) — one readable line, no trace.
        logger.warning("local OCR (%s) failed: %s", backend, str(exc).splitlines()[0] if str(exc) else type(exc).__name__)
        return None
    lines = group_rows(frags)
    result = OcrResult(lines=lines, text="\n".join(ln.text for ln in lines), engine=backend, image_size=size, fragments=deskew(frags, size))
    _CACHE[key] = result
    while len(_CACHE) > _CACHE_SIZE:
        _CACHE.popitem(last=False)
    return result


__all__ = ["OCR_BACKEND_ENV", "OcrLine", "OcrResult", "deskew", "group_rows", "page_angle", "ocr_available", "ocr_backend", "ocr_image", "clear_cache"]
