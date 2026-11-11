"""PHOTO drops with the REAL local stack (RapidOCR, YOLOX, qwen2.5vl:3b,
qwen3:8b) — provider=local, cloud blocked. Every photo must be read locally:
the response's image pipeline is never "cloud"."""
import pytest

from tests.claude import photos_cases


@pytest.mark.parametrize("check", photos_cases.ALL, ids=lambda f: f.__name__.removeprefix("check_"))
def test_local(client, check):
    r = check(client, "local")
    assert r.get("pipeline") != "cloud", f"local mode must never read a photo in the cloud: pipeline={r.get('pipeline')!r}"
