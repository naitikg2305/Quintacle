from __future__ import annotations

import os

# Routine structured tasks (journal parsing, KB sorting) default to a cheap
# model — swap via env var, no code change, when more power is needed.
DEFAULT_MODEL = os.environ.get("QUINTACLE_LLM_MODEL", "claude-haiku-4-5")

# Reserved for heavier "research" tasks (e.g. the KB-grounded chat) — a
# separate knob so bumping this up doesn't also make routine parsing pricier.
RESEARCH_MODEL = os.environ.get("QUINTACLE_LLM_RESEARCH_MODEL", "claude-sonnet-5")
