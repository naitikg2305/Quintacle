"""File drops beyond plain PDFs (docx/xlsx/pptx, .md + its image, PDF
metadata, scanned PDF) with the REAL local models — provider=local, cloud
blocked (a step that only works with Claude fails with "cloud call blocked")."""
import pytest

from tests.claude import files_cases


@pytest.mark.parametrize("check", files_cases.ALL, ids=lambda f: f.__name__.removeprefix("check_"))
def test_local(client, check):
    r = check(client, "local")
    assert r.get("pipeline") != "cloud", f"local mode answered from the cloud: pipeline={r.get('pipeline')!r}"
