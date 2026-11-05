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

# Local model for ingest/parse calls (llm_dispatch.py reads it; the desktop
# default is qwen3:8b). 2026-11-05: the phone default is qwen3:4b — the
# 1.5B tier mangles multi-entry schemas (llm_dispatch.py's own note), and 4B
# fits the 12 GB S25U. install-ollama-termux.sh pulls both qwen3:4b and
# qwen2.5:1.5b (the fast chat fallback).
export QUINTACLE_LOCAL_PARSE_MODEL="${QUINTACLE_LOCAL_PARSE_MODEL:-qwen3:4b}"

# Ingest provider: auto = local when the daemon answers, cloud otherwise
# (escalation re-runs from the original input, per the local-first rule).
export QUINTACLE_INGEST_PROVIDER="${QUINTACLE_INGEST_PROVIDER:-auto}"

# Perception (Tier 2, 2026-11-05): YOLOX-nano tags + SCRFD face detect +
# ArcFace embed on LiteRT instead of onnxruntime. Runtime comes from
# `pkg install python-tflite-runtime` (scripts/termux/setup-perception.sh);
# models are the converted .tflite files under
# $QUINTACLE_DATA_DIR/perception/models/tflite/ (they ride along in the
# migrate-export tarball). dynamic_range_quant = int8 weights, the phone
# target (parity-proven vs ONNX in phone/tier2-perception-tflite/README.md).
# If the runtime or models are missing, perceive_photo() just returns None
# with one warning — drops keep working.
export QUINTACLE_PERCEPTION_BACKEND="${QUINTACLE_PERCEPTION_BACKEND:-tflite}"
export QUINTACLE_TFLITE_VARIANT="${QUINTACLE_TFLITE_VARIANT:-dynamic_range_quant}"

# Claude Max on the phone is best-effort: max_backend.py looks for `claude`
# on PATH (scripts/termux/setup-claude-max.sh installs a proot wrapper there).
# No wrapper -> every cloud call goes straight to the API key in core/.env.
