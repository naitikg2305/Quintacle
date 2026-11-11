"""REAL local models (Ollama), cloud blocked, sandbox seeded with presets."""
import pytest

from tests.claude import cases
from tests.claude.harness import make_client, missing_requirements


def pytest_collection_modifyitems(config, items):
    reason = missing_requirements()
    if reason:
        for item in items:
            item.add_marker(pytest.mark.skip(reason=reason))


@pytest.fixture(scope="session")
def client(tmp_path_factory):
    c = make_client(tmp_path_factory.mktemp("local"))
    cases.seed(c)
    return c
