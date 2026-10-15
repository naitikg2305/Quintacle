"""Cheap deterministic scene attributes — the "sunny day" class of facts.

No model, no LLM, no randomness: EXIF time-of-day + pixel statistics over a
downscaled copy. Every value is honest about uncertainty — None means "can't
tell from this photo", never a guess.
"""

from __future__ import annotations

from datetime import datetime

from PIL import Image

# EXIF capture hour within [start, end) counts as daylight. Deliberately wide
# (civil daylight across seasons) — this is a hint, not an ephemeris.
_DAYLIGHT_START_HOUR = 7
_DAYLIGHT_END_HOUR = 19

# A top-of-frame pixel counts as "sky-like" when it's bright and blue-leaning
# (clear sky) or near-white (overcast). If more than this fraction of the top
# strip is sky-like, the photo gets outdoor_hint=True; below it we say None —
# plenty of outdoor shots have no visible sky, so absence proves nothing.
_SKY_FRACTION_FOR_OUTDOOR = 0.30
_ANALYSIS_SIZE = 64  # pixel stats over a 64x64 thumbnail — plenty, and O(1)


def _exif_capture_hour(img: Image.Image) -> int | None:
    """Hour-of-day from the same EXIF tags drop.py's extract_photo_date reads
    (DateTimeOriginal/DateTimeDigitized in the Exif sub-IFD, then base
    DateTime)."""
    try:
        exif = img.getexif()
        candidates = []
        try:
            exif_ifd = exif.get_ifd(0x8769)
            for tag in (36867, 36868):  # DateTimeOriginal, DateTimeDigitized
                if tag in exif_ifd:
                    candidates.append(exif_ifd[tag])
        except Exception:
            pass
        if 306 in exif:  # DateTime
            candidates.append(exif[306])
        for raw in candidates:
            try:
                return datetime.strptime(str(raw), "%Y:%m:%d %H:%M:%S").hour
            except ValueError:
                continue
    except Exception:
        pass
    return None


def analyze_scene(img: Image.Image) -> dict:
    """Returns {"daylight": bool|None, "outdoor_hint": bool|None, "brightness": float}.

    - daylight: from EXIF capture hour; None when the photo carries no EXIF
      timestamp (screenshots, stripped re-shares).
    - outdoor_hint: True when the top of the frame looks like sky; None
      otherwise (never False — no visible sky doesn't mean indoors).
    - brightness: mean luma of the whole frame, 0.0-1.0.
    """
    hour = _exif_capture_hour(img)
    daylight = (_DAYLIGHT_START_HOUR <= hour < _DAYLIGHT_END_HOUR) if hour is not None else None

    small = img.convert("RGB").resize((_ANALYSIS_SIZE, _ANALYSIS_SIZE))
    raw = small.tobytes()  # packed RGB triplets (getdata() is deprecated in Pillow 12+)
    pixels = [(raw[i], raw[i + 1], raw[i + 2]) for i in range(0, len(raw), 3)]
    lumas = [0.299 * r + 0.587 * g + 0.114 * b for r, g, b in pixels]
    brightness = sum(lumas) / (len(lumas) * 255.0)

    top_rows = _ANALYSIS_SIZE // 4  # top 25% of the frame
    sky_like = 0
    top_count = top_rows * _ANALYSIS_SIZE
    for i in range(top_count):
        r, g, b = pixels[i]
        luma = lumas[i]
        clear_sky = b > r + 10 and b >= g and luma > 110
        overcast = luma > 225
        if clear_sky or overcast:
            sky_like += 1
    outdoor_hint = True if (sky_like / top_count) > _SKY_FRACTION_FOR_OUTDOOR else None

    return {"daylight": daylight, "outdoor_hint": outdoor_hint, "brightness": round(brightness, 4)}
