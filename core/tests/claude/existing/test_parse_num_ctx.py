"""2026-11-11: parsing runs at 8k context, stepping up to 16k only when a
request needs it (qwen3:8b at 16k + qwen2.5vl don't fit in 12 GB)."""
from quintacle_core.llm_dispatch import PARSE_NUM_CTX, PARSE_NUM_CTX_LARGE, parse_num_ctx


def test_normal_drop_uses_8k():
    assert parse_num_ctx("s" * 3000, "u" * 9000, 1024) == PARSE_NUM_CTX == 8192


def test_big_request_steps_up_to_16k():
    assert parse_num_ctx("s" * 3000, "u" * 20000, 1024) == PARSE_NUM_CTX_LARGE == 16384


def test_output_cap_counts():
    assert parse_num_ctx("s", "u" * 12000, 4096) == PARSE_NUM_CTX_LARGE
