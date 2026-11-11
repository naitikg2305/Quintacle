"""REAL Claude through the Max subscription (provider=cloud). The metered-API
fallback is blocked, so these never spend API money; they do use Max usage."""
import pytest

from tests.claude import cases
from tests.claude.harness import make_client, missing_max


def pytest_collection_modifyitems(config, items):
    reason = missing_max()
    if reason:
        for item in items:
            item.add_marker(pytest.mark.skip(reason=reason))


@pytest.fixture(scope="session")
def client(tmp_path_factory):
    c = make_client(tmp_path_factory.mktemp("max"), cloud=True)
    cases.seed(c)
    return c
