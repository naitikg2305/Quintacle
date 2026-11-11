"""PEOPLE mentions, photo PERCEPTION, label-less FOOD photos and image-KIND
routing with REAL Claude via Max — provider=cloud; each test proves a Max
call actually happened (no silent local answer, no API spend), and every
check that reads an image reports the "cloud" pipeline. Perception (YOLO
tags, faces, scene) is local-only by design and runs in this mode too."""
import pytest

from tests.claude import people_photos_cases
from tests.claude.harness import MAX_CALLS


@pytest.mark.parametrize("check", people_photos_cases.ALL, ids=lambda f: f.__name__.removeprefix("check_"))
def test_max(client, check):
    before = len(MAX_CALLS)
    r = check(client, "cloud")
    assert len(MAX_CALLS) > before, "Claude (Max) was never called"
    if check in people_photos_cases.PHOTO_CHECKS:
        assert r.get("pipeline") == "cloud", f"provider=cloud must read the photo with Claude: pipeline={r.get('pipeline')!r}"
