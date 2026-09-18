from __future__ import annotations

import anthropic
from pydantic import BaseModel

from ...llm_config import DEFAULT_MODEL

# The domains named in the planning doc (quintacle-ideas.md, Pillar 3), nested
# under the real Notebook's own top-level buckets — offered even before any
# folder actually exists on disk, so the first few pushes land somewhere
# sensible instead of every entry inventing its own new top-level folder.
SEED_FOLDERS = [
    "Career/Career & Education",
    "Personal Development/Physical/Fitness",
    "Personal Development/Physical/Nutrition",
    "Personal Development/Physical/Grooming",
    "Personal Development/Physical/Style & Dressing",
    "Personal Development/Mental/Mental Models",
    "Personal Development/Mental/Relationships",
    "Planning/Social Planning/Social & Dating",
    "Planning/Travel",
    "Organisation/Finance/Life Planning",
    "Organisation/Finance/Stocks & Investments",
    "Organisation/Finance/Major Purchases",
    "Multimedia/Media & Entertainment",
    "Multimedia/Social Media Planning",
    "Nerd Folder/Projects",
    "Nerd Folder/Business",
    "Sports & Activities",
]

def _format_notes_index(existing_notes: list[dict]) -> str:
    if not existing_notes:
        return "Existing notes: (none saved yet)"
    lines = [f"{n['title']!r} ({n['folder']})" for n in existing_notes]
    return "Existing notes (for the links field below):\n" + "\n".join(lines)


_LINKS_INSTRUCTION = (
    "- links: titles of any existing notes above that this is genuinely related to (list, may "
    "be empty) — for graphing connections, not decoration. Only include real, substantive "
    "relationships, not vague topical overlap."
)

_SYSTEM_PROMPT = """You help file a piece of personal knowledge into the right folder of a \
personal knowledge base. Given a list of folders (some may already have entries, some are \
just suggestions that don't exist yet) and a piece of freeform text — a scratchpad note, a \
thought worked out over a chat — suggest:

- folder: the best fit from the list, OR a short new folder name (2-3 words, Title Case) if \
  nothing offered actually fits. Prefer an existing folder over inventing one.
- title: a short descriptive title for this entry — becomes the filename.
- content: the text cleaned up into a well-formatted markdown note. Trim filler and false \
  starts, keep the actual substance and the person's own voice — don't pad it with generic \
  advice they didn't write. You may naturally reference a related existing note inline as \
  [[Note Title]] where it reads well, but this is cosmetic — the links field below is what \
  actually drives the graph.
""" + _LINKS_INSTRUCTION


class KBSuggestion(BaseModel):
    folder: str
    title: str
    content: str
    links: list[str] = []


def suggest_kb_entry(raw_text: str, existing_folders: list[str], existing_notes: list[dict] | None = None) -> KBSuggestion:
    client = anthropic.Anthropic()
    offered = sorted(set(existing_folders) | set(SEED_FOLDERS))
    system = _SYSTEM_PROMPT + "\n\nFolders: " + ", ".join(offered) + "\n\n" + _format_notes_index(existing_notes or [])
    response = client.messages.parse(
        model=DEFAULT_MODEL,
        max_tokens=4096,
        system=system,
        messages=[{"role": "user", "content": raw_text}],
        output_format=KBSuggestion,
    )
    return response.parsed_output


_SCOPED_SYSTEM_PROMPT = """You help write a note that's going into a folder the user has \
already chosen — you're NOT deciding where it goes, only how to write it up. Given freeform \
text (from a chat scoped to that folder, or typed directly), suggest:

- title: a short descriptive title for this entry — becomes the filename.
- content: the text cleaned up into a well-formatted markdown note. Trim filler and false \
  starts, keep the actual substance and the person's own voice.
""" + _LINKS_INSTRUCTION


class ScopedKBSuggestion(BaseModel):
    title: str
    content: str
    links: list[str] = []


def suggest_kb_entry_for_folder(raw_text: str, existing_notes: list[dict] | None = None) -> ScopedKBSuggestion:
    """Like suggest_kb_entry(), but the folder is already fixed by the caller
    (a folder-scoped chat) — no folder guessing, deterministic destination.
    Links can still point anywhere in the KB — a note about someone can
    genuinely relate to a note filed elsewhere, scoping the chat's context
    doesn't mean the graph has to be scoped too."""
    client = anthropic.Anthropic()
    system = _SCOPED_SYSTEM_PROMPT + "\n\n" + _format_notes_index(existing_notes or [])
    response = client.messages.parse(
        model=DEFAULT_MODEL,
        max_tokens=4096,
        system=system,
        messages=[{"role": "user", "content": raw_text}],
        output_format=ScopedKBSuggestion,
    )
    return response.parsed_output


_PLACEMENT_SYSTEM_PROMPT = """You help file an already-finished document into the right folder \
of a personal knowledge base. You do NOT edit or rewrite its content — the user doesn't want \
an already-written document touched. Given a list of folders and the document's text, suggest:

- folder: the best fit from the list, OR a short new folder name (2-3 words, Title Case) if \
  nothing offered actually fits. Prefer an existing folder over inventing one.
- title: a short descriptive title for this entry — becomes the filename.
""" + _LINKS_INSTRUCTION


class KBPlacement(BaseModel):
    folder: str
    title: str
    links: list[str] = []


def suggest_kb_placement(
    raw_text: str, existing_folders: list[str], existing_notes: list[dict] | None = None
) -> KBPlacement:
    """Like suggest_kb_entry(), but never touches the content — for a document
    the user considers already finished (an itinerary, a report) and doesn't
    want AI rewording. Ask before letting AI edit finished work. Links still
    get suggested — they live in frontmatter, not the body, so the document
    stays byte-for-byte untouched but still gains graph connectivity."""
    client = anthropic.Anthropic()
    offered = sorted(set(existing_folders) | set(SEED_FOLDERS))
    system = _PLACEMENT_SYSTEM_PROMPT + "\n\nFolders: " + ", ".join(offered) + "\n\n" + _format_notes_index(existing_notes or [])
    response = client.messages.parse(
        model=DEFAULT_MODEL,
        max_tokens=1024,
        system=system,
        messages=[{"role": "user", "content": raw_text}],
        output_format=KBPlacement,
    )
    return response.parsed_output


_BATCH_SYSTEM_PROMPT = """You help file a BATCH of files into a personal knowledge base at once. \
You'll get each file's opaque file_id and its extracted content/description. Given a list of \
folders (some already have entries, some are just suggestions), propose for EVERY file:

- file_id: copy this EXACTLY as given (e.g. "file_0") — it's an opaque reference id, not a name,
  never rename or reformat it.
- folder: the best fit from the list, OR a short new folder name (2-3 words, Title Case) if \
  nothing offered actually fits. Prefer an existing folder over inventing one.
- title: a short descriptive title for this note.
- content: the text cleaned up into a well-formatted markdown note.
- trip_name: ONLY for a photo that's clearly part of a specific trip/event you can identify from
  it and its siblings (e.g. "Tokyo Trip 2026") — else leave empty. This overrides where the
  actual photo file gets saved (by date/trip, not by this folder field), so only set it when
  you're confident multiple photos in this batch belong to the same identifiable trip.
""" + _LINKS_INSTRUCTION + """ Also link between files WITHIN this same batch when they're
genuinely related (e.g. two files about the same stock) — you see them all at once, use that.

IMPORTANT: since you see every file at once, group related files under the EXACT SAME folder \
string — don't invent near-duplicate folder names for files that clearly belong together (e.g. \
don't split "Organisation/Finance/Stocks & Investments" and "Finance/Stock Notes" — pick one \
and reuse it for every file that fits). Also use the exact same trip_name for every photo from
the same trip — don't vary the wording between siblings."""


class BatchFileSuggestion(BaseModel):
    file_id: str
    folder: str
    title: str
    content: str
    links: list[str] = []
    trip_name: str = ""


class BatchDropSuggestion(BaseModel):
    files: list[BatchFileSuggestion]


def suggest_kb_batch(
    file_entries: list[dict], existing_folders: list[str], existing_notes: list[dict] | None = None
) -> BatchDropSuggestion:
    """file_entries: [{"file_id": ..., "description": ...}, ...]. One call
    covering every file so related files consistently land in the same
    folder — N independent single-file calls would risk near-duplicate
    folder names (e.g. "Stocks & Investments" vs "Stock Notes") since each
    call can't see what its siblings decided. file_id is an opaque token
    (not the real filename) — models reliably echo an opaque id back
    unchanged, but will happily "improve" something that looks like a name,
    which broke the original design (real filenames came back renamed)."""
    client = anthropic.Anthropic()
    offered = sorted(set(existing_folders) | set(SEED_FOLDERS))
    system = (
        _BATCH_SYSTEM_PROMPT + "\n\nFolders: " + ", ".join(offered) + "\n\n" + _format_notes_index(existing_notes or [])
    )
    user_content = "\n\n".join(f"### {e['file_id']}\n{e['description']}" for e in file_entries)
    response = client.messages.parse(
        model=DEFAULT_MODEL,
        max_tokens=16000,
        system=system,
        messages=[{"role": "user", "content": user_content}],
        output_format=BatchDropSuggestion,
    )
    return response.parsed_output


_UPDATE_SYSTEM_PROMPT = (
    "You maintain one note in a personal knowledge base. You'll be given the "
    "note's current body and new information to fold in. Produce the updated "
    "body — merge naturally, don't just append to the end; remove anything the "
    "new information explicitly supersedes, keep everything else that's still "
    "true. Do not include a '# Title' heading — that's handled separately. "
    "Return only the updated body content."
)


class KBBodyUpdate(BaseModel):
    body: str


def suggest_kb_update(existing_body: str, new_text: str) -> str:
    client = anthropic.Anthropic()
    response = client.messages.parse(
        model=DEFAULT_MODEL,
        max_tokens=4096,
        system=_UPDATE_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"CURRENT NOTE BODY:\n{existing_body}\n\nNEW INFORMATION TO FOLD IN:\n{new_text}",
            }
        ],
        output_format=KBBodyUpdate,
    )
    return response.parsed_output.body
