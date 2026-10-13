from __future__ import annotations

from typing import Any

# The graph/edge-linking engine (docs/graph-model.md) is being built in a
# separate parallel worktree and doesn't exist in this one yet. Per
# graph-model.md's "two deterministic rules", every MCP write should attempt
# to link what it just wrote into the graph — so every write tool calls this
# function. Until the real module lands at core/quintacle_core/graph.py (or a
# graph/ package) exposing `link_new_entry` with this signature, the import
# fails and this is a documented no-op rather than a crash.
#
# Assumed signature, for whoever wires up the real implementation:
#
#   def link_new_entry(
#       entry_type: str,       # "journal_day" | "kb_note" | "todo" | "expense" | ...
#       entry_id: str,         # stable id the graph should key on, e.g.
#                              # "journal:2026-10-13", "note:Folder/slug", a todo id
#       text: str,             # the freeform text/body of what was just written,
#                              # for the linking step to match against other entries
#       **context: Any,        # folder, declared links, date, etc. — whatever
#                              # extra context is cheap to pass and might help
#   ) -> list[str]:            # ids/paths of edges created (graph/edges/*.md per
#                              # graph-model.md Stage 1), or [] if nothing linked
#       ...
#
# An edit/delete that changes what something links to is itself just another
# write under this same contract (per graph-model.md) — not handled specially
# here; call link_new_entry again with the updated text/links once that path
# exists, same as a create.


def link_new_entry(entry_type: str, entry_id: str, text: str, **context: Any) -> list[str]:
    try:
        from ..graph import link_new_entry as _real_link_new_entry
    except ImportError:
        return []
    try:
        return _real_link_new_entry(entry_type, entry_id, text, **context)
    except Exception:
        # A write must never fail because the linking step broke — same
        # "additive, never blocking" spirit as api.py's Experience/Person
        # drop-router checks.
        return []
