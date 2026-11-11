"""KB chat with the REAL local model (local:qwen3:8b via Ollama), cloud
blocked — fact recall, private notes allowed locally, transcript autosave."""
import pytest

from tests.claude import chat_cases


@pytest.mark.parametrize("check", chat_cases.ALL, ids=lambda f: f.__name__.removeprefix("check_"))
def test_chat_local(client, check):
    check(client, "local")
