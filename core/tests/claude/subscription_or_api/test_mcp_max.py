"""END-TO-END with real Claude (Max subscription): headless `claude -p` with
Quintacle's MCP server attached to the SANDBOX data dir, asked in plain
words to save a note; the note must land in the sandbox store through the
MCP write path (ledgered), and the real ~/.quintacle must be untouched.

Server launch mirrors `claude mcp get quintacle` (user scope):
  command: core/.venv/bin/python   args: -m quintacle_core.mcp_server
  env:     PYTHONPATH=core
plus QUINTACLE_DATA_DIR=<sandbox> passed via --mcp-config, so it can never
fall back to ~/.quintacle.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

from quintacle_core.mcp_server.ledger import Ledger
from quintacle_core.nodes.kb.store import KBStore
from tests.claude import mcp_cases
from tests.claude.harness import REAL_STORE

ALLOWED = [f"mcp__quintacle__{t}" for t in ("kb_create_entry", "kb_list_folders", "kb_search_entries", "kb_get_entry")]


def _stamp(p: Path):
    return (p.stat().st_size, p.stat().st_mtime_ns) if p.exists() else None


def test_claude_saves_note_via_mcp_into_sandbox(client, tmp_path):
    """Asked to save a titled note, Claude must call kb_create_entry on the sandbox server -> one ledgered note there."""
    data = mcp_cases.sandbox_dir()
    kb = KBStore(data / "kb")
    assert kb.read_full(mcp_cases.E2E_FOLDER, mcp_cases.E2E_SLUG) is None, "precondition: fresh sandbox"

    python = mcp_cases.CORE_DIR / ".venv" / "bin" / "python"
    server_env = {
        "PYTHONPATH": str(mcp_cases.CORE_DIR),
        "QUINTACLE_DATA_DIR": str(data),
        "QUINTACLE_MCP_CLIENT": mcp_cases.E2E_CLIENT,
    }
    config = {"mcpServers": {"quintacle": {
        "type": "stdio",
        "command": str(python if python.exists() else Path(sys.executable)),
        "args": ["-m", "quintacle_core.mcp_server"],
        "env": server_env,
    }}}

    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}  # bill Max, never the API
    env.update(server_env)  # belt and braces: the child inherits the sandbox too

    real_ledger = REAL_STORE / "mcp-log.md"
    real_note = REAL_STORE / "kb" / "tests" / "mcp" / f"{mcp_cases.E2E_SLUG}.md"
    before = (_stamp(real_ledger), real_note.exists())

    cmd = [
        os.environ.get("QUINTACLE_CLAUDE_BIN", "claude"), "-p", mcp_cases.E2E_PROMPT,
        "--output-format", "json",
        "--strict-mcp-config", "--mcp-config", json.dumps(config),
        "--setting-sources", "",
        "--allowedTools", *ALLOWED,
        "--no-session-persistence",
    ]
    proc = subprocess.run(cmd, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=600)
    report = f"exit={proc.returncode}\nstdout={proc.stdout[-2000:]}\nstderr={proc.stderr[-2000:]}"
    assert proc.returncode == 0, report

    # The note exists in the SANDBOX with the requested title and body.
    entry = kb.read_full(mcp_cases.E2E_FOLDER, mcp_cases.E2E_SLUG)
    assert entry is not None, f"note not in sandbox; folders={kb.list_folders()}\n{report}"
    assert entry["title"] == mcp_cases.E2E_TITLE, entry
    assert "hello" in entry["content"].lower(), entry["content"]

    # It came through the sandbox MCP server's write path: one active ledger entry from our client.
    writes = [e for e in Ledger(data / "mcp-log.md").all() if e.tool == "kb.create_entry" and e.result.get("slug") == mcp_cases.E2E_SLUG]
    assert len(writes) == 1 and writes[0].client == mcp_cases.E2E_CLIENT and writes[0].undone_at is None, writes

    # The real store was never touched.
    assert (_stamp(real_ledger), real_note.exists()) == before, "the real ~/.quintacle changed during the run"
