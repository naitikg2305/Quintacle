"""PEOPLE mentions, photo PERCEPTION, label-less FOOD photos and image-KIND
routing with the REAL local stack (qwen3:8b, qwen2.5vl:3b, RapidOCR, YOLOX) —
provider=local, cloud blocked. Nothing may be read in the cloud: the image
pipeline is never "cloud"."""
import pytest

from tests.claude import people_photos_cases


@pytest.mark.parametrize("check", people_photos_cases.ALL, ids=lambda f: f.__name__.removeprefix("check_"))
def test_local(client, check):
    r = check(client, "local")
    assert r.get("pipeline") != "cloud", f"local mode must never read a photo in the cloud: pipeline={r.get('pipeline')!r}"
