"""2026-11-17 (owner, T5): an AVIF photo named .jpg is converted to JPEG at the drop."""
import io
from pathlib import Path

from PIL import Image

from quintacle_core.nodes.drop_router import normalize_image

LAMB = Path(__file__).parents[2] / "tests" / "user" / "files" / "food" / "lamb-label-2026-11-17" / "13455__2.jpg"


def _img(fmt: str) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(buf, fmt)
    return buf.getvalue()


def test_avif_named_jpg_becomes_jpeg():
    data, name = normalize_image(_img("AVIF"), "label.jpg")
    assert data[:3] == b"\xff\xd8\xff" and name == "label.jpg"


def test_the_owners_lamb_photo_becomes_jpeg():
    if not LAMB.exists():
        return
    data, name = normalize_image(LAMB.read_bytes(), LAMB.name)
    assert data[:3] == b"\xff\xd8\xff" and Image.open(io.BytesIO(data)).size[0] > 100


def test_a_real_jpeg_and_non_images_are_untouched():
    jpg = _img("JPEG")
    assert normalize_image(jpg, "a.jpg") == (jpg, "a.jpg")
    assert normalize_image(b"%PDF-1.7", "a.pdf") == (b"%PDF-1.7", "a.pdf")


def test_png_named_jpg_gets_its_real_extension():
    png = _img("PNG")
    assert normalize_image(png, "a.jpg") == (png, "a.png")
