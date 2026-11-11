"""Finance text + statement drops with the REAL local models — provider=local,
cloud blocked. check_statement_pdf is a KNOWN GAP here (PDF statements only
have a cloud lane today); it asserts the correct local read and is expected
to fail until a local PDF-statement lane exists."""
import pytest

from tests.claude import finance_cases


@pytest.mark.parametrize("check", finance_cases.ALL, ids=lambda f: f.__name__.removeprefix("check_"))
def test_local(client, check):
    check(client, "local")
