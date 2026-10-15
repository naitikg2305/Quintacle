# shellcheck shell=bash
# Quintacle — Tier 1 phone environment profile. SOURCED, not executed:
# scripts/termux/start-backend.sh sources this file automatically when it
# exists, so every env knob below reaches uvicorn without editing that
# script. Harmless to source on a desktop shell too (it only exports vars).
#
# Every export respects a value you've already set in the shell, so
# per-session overrides win over this file.

# Where the `local:` chat models live (nodes/kb/chat.py → ollama_host()).
# Loopback, matching ollama's own default bind and the backend's
# 127.0.0.1-only uvicorn — stated explicitly so the intent survives even if
# someone sets a LAN-wide OLLAMA_HOST in their shell profile.
export QUINTACLE_OLLAMA_HOST="${QUINTACLE_OLLAMA_HOST:-http://127.0.0.1:11434}"

# Vision dispatch (nodes/kb/drop.py): try the local VLM first, fall back to
# the cloud caption with a log line when it isn't available. On the phone
# the local VLM is a Tier 3 deliverable (phone/tier3-*) — until that lands
# on-device, "auto" simply means photo drops keep working via cloud, and
# they switch to local automatically the day Tier 3's model is pulled.
export QUINTACLE_VISION="${QUINTACLE_VISION:-auto}"

# Local model for ingest/parse calls. The ingest dispatch that reads this is
# landing from a parallel workstream and is NOT in this tree yet — setting
# it here is forward wiring, effective once that merges; until then it's an
# inert env var. qwen2.5:1.5b is the Tier 1 default model
# (install-ollama-termux.sh pulls it), good for narration/single-entry
# parses per docs/local-llm-phone-plan.md.
export QUINTACLE_LOCAL_PARSE_MODEL="${QUINTACLE_LOCAL_PARSE_MODEL:-qwen2.5:1.5b}"

# Ingest provider selection — same parallel workstream, same "effective once
# merged" caveat as above. "auto" is expected to mean local-when-available,
# cloud otherwise, mirroring QUINTACLE_VISION's contract.
export QUINTACLE_INGEST_PROVIDER="${QUINTACLE_INGEST_PROVIDER:-auto}"
