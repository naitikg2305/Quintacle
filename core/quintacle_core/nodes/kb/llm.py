from __future__ import annotations

from pydantic import BaseModel

from ...llm_dispatch import parse_structured

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


def suggest_kb_entry(
    raw_text: str, existing_folders: list[str], existing_notes: list[dict] | None = None, provider: str | None = None
) -> KBSuggestion:
    offered = sorted(set(existing_folders) | set(SEED_FOLDERS))
    system = _SYSTEM_PROMPT + "\n\nFolders: " + ", ".join(offered) + "\n\n" + _format_notes_index(existing_notes or [])
    return parse_structured(system, raw_text, KBSuggestion, provider=provider, max_tokens=4096).parsed


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


def suggest_kb_entry_for_folder(
    raw_text: str, existing_notes: list[dict] | None = None, provider: str | None = None
) -> ScopedKBSuggestion:
    """Like suggest_kb_entry(), but the folder is already fixed by the caller
    (a folder-scoped chat) — no folder guessing, deterministic destination.
    Links can still point anywhere in the KB — a note about someone can
    genuinely relate to a note filed elsewhere, scoping the chat's context
    doesn't mean the graph has to be scoped too."""
    system = _SCOPED_SYSTEM_PROMPT + "\n\n" + _format_notes_index(existing_notes or [])
    return parse_structured(system, raw_text, ScopedKBSuggestion, provider=provider, max_tokens=4096).parsed


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
    raw_text: str, existing_folders: list[str], existing_notes: list[dict] | None = None, provider: str | None = None
) -> KBPlacement:
    """Like suggest_kb_entry(), but never touches the content — for a document
    the user considers already finished (an itinerary, a report) and doesn't
    want AI rewording. Ask before letting AI edit finished work. Links still
    get suggested — they live in frontmatter, not the body, so the document
    stays byte-for-byte untouched but still gains graph connectivity."""
    offered = sorted(set(existing_folders) | set(SEED_FOLDERS))
    system = _PLACEMENT_SYSTEM_PROMPT + "\n\nFolders: " + ", ".join(offered) + "\n\n" + _format_notes_index(existing_notes or [])
    return parse_structured(system, raw_text, KBPlacement, provider=provider, max_tokens=1024).parsed


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
    file_entries: list[dict], existing_folders: list[str], existing_notes: list[dict] | None = None, provider: str | None = None
) -> BatchDropSuggestion:
    """file_entries: [{"file_id": ..., "description": ...}, ...]. One call
    covering every file so related files consistently land in the same
    folder — N independent single-file calls would risk near-duplicate
    folder names (e.g. "Stocks & Investments" vs "Stock Notes") since each
    call can't see what its siblings decided. file_id is an opaque token
    (not the real filename) — models reliably echo an opaque id back
    unchanged, but will happily "improve" something that looks like a name,
    which broke the original design (real filenames came back renamed)."""
    offered = sorted(set(existing_folders) | set(SEED_FOLDERS))
    system = (
        _BATCH_SYSTEM_PROMPT + "\n\nFolders: " + ", ".join(offered) + "\n\n" + _format_notes_index(existing_notes or [])
    )
    user_content = "\n\n".join(f"### {e['file_id']}\n{e['description']}" for e in file_entries)
    return parse_structured(system, user_content, BatchDropSuggestion, provider=provider, max_tokens=16000).parsed


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


_RECORD_RULES = (
    "Extract ONLY what's worth keeping — decisions made (with the why), conclusions, "
    "concrete facts and preferences stated, and genuinely open questions — as tight "
    "markdown bullet points in the person's own voice. Never invent numbers, dates, or "
    "facts that aren't in the conversation; skip pleasantries, false starts, and dead "
    "ends. If a point supersedes something older, state it as a plain update (\"now X, "
    "was Y\") rather than pretending the old state never existed. Do NOT include any "
    "date or title heading — those are added separately, in code."
)

_RECORD_SCOPED_SYSTEM_PROMPT = (
    "You distill a chat conversation into a short dated entry that will be APPENDED to "
    "one existing note in a personal knowledge base (its title is given — the note is a "
    "running decision log; history is never rewritten). " + _RECORD_RULES + " Return just:\n"
    "- points: the markdown bullet points."
)


class RecordFoldPoints(BaseModel):
    points: str


_RECORD_UNSCOPED_SYSTEM_PROMPT = (
    "You distill a chat conversation into a short dated entry for a personal knowledge "
    "base — the user will pick/confirm where it's filed. " + _RECORD_RULES + " Return:\n"
    "- folder: the best fit from the folder list, OR a short new folder name (2-3 words, "
    "Title Case) if nothing fits. Prefer an existing folder.\n"
    "- title: a short descriptive title for the topic this conversation was about — if an "
    "existing note already covers this exact topic, use ITS title so the entry lands there.\n"
    "- points: the markdown bullet points."
)


class RecordFoldNew(BaseModel):
    folder: str
    title: str
    points: str


def suggest_record_fold(
    conversation_text: str, topic_title: str | None = None, provider: str | None = None
) -> RecordFoldPoints:
    """\"Record that\" (next-wave-plan §4), scoped: the chat is already on a
    note — the model ONLY writes the bullet points; folder/title/date are
    fixed by code. Local-first via parse_structured's normal routing."""
    system = _RECORD_SCOPED_SYSTEM_PROMPT + f"\n\nThe note being appended to: {topic_title!r}"
    return parse_structured(system, conversation_text, RecordFoldPoints, provider=provider, max_tokens=4096).parsed


def suggest_record_fold_new(
    conversation_text: str,
    existing_folders: list[str],
    existing_notes: list[dict] | None = None,
    provider: str | None = None,
) -> RecordFoldNew:
    """\"Record that\" with no scoped topic: the model also proposes a folder
    and title (reviewed/edited by the user before anything writes — same
    propose→review→Save gate as every other KB write)."""
    offered = sorted(set(existing_folders) | set(SEED_FOLDERS))
    system = (
        _RECORD_UNSCOPED_SYSTEM_PROMPT + "\n\nFolders: " + ", ".join(offered) + "\n\n" + _format_notes_index(existing_notes or [])
    )
    return parse_structured(system, conversation_text, RecordFoldNew, provider=provider, max_tokens=4096).parsed


def suggest_kb_update(existing_body: str, new_text: str, provider: str | None = None) -> str:
    result = parse_structured(
        _UPDATE_SYSTEM_PROMPT,
        f"CURRENT NOTE BODY:\n{existing_body}\n\nNEW INFORMATION TO FOLD IN:\n{new_text}",
        KBBodyUpdate,
        provider=provider,
        max_tokens=4096,
    )
    return result.parsed.body
