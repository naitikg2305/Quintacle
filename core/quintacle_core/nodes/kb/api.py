from __future__ import annotations

import base64
import mimetypes
import re
import urllib.request
from datetime import date
from typing import Literal

from fastapi import APIRouter, Body, File, Form, HTTPException, Response, UploadFile
from openai import OpenAIError
from pydantic import BaseModel

from ..journal.api import get_store as get_journal_store
from ..profile.api import get_store as get_profile_store
from .chat import CHAT_MODELS, UnknownModelError, run_kb_chat
from .chat_store import ChatStore
from .drop import describe_drop, extract_photo_date, extract_photo_location, is_image
from .image_gen import generate_image
from .llm import suggest_kb_batch, suggest_kb_entry, suggest_kb_entry_for_folder, suggest_kb_update
from .photo_organizer import compute_photo_folder
from .spreadsheet import read_spreadsheet, write_spreadsheet
from .store import KBStore, _ASSET_LINES_RE
from .view import ViewConfig, infer_view

_MD_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\((https?://[^)\s]+)\)")


def _localize_remote_images(content: str, folder: str, store: KBStore) -> str:
    """Chat can produce markdown with remote image links (e.g. a Wikipedia
    photo illustrating something it mentioned) — pushing that into the KB
    downloads and stores the actual bytes instead of leaving a live URL, the
    same "self-contained, works with zero internet" guarantee every other
    asset in this app already has. A failed download leaves the original
    link alone rather than breaking the whole push."""

    def replace(match: re.Match) -> str:
        alt, url = match.group(1), match.group(2)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Quintacle/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = resp.read()
                content_type = resp.headers.get("Content-Type", "")
        except Exception:
            return match.group(0)
        ext = mimetypes.guess_extension(content_type.split(";")[0].strip()) or ".jpg"
        asset_path = store.save_asset(folder, f"{alt or 'image'}{ext}", data)
        return f"![{alt}]({asset_path})"

    return _MD_IMAGE_RE.sub(replace, content)


router = APIRouter(prefix="/kb", tags=["kb"])
_store: KBStore | None = None
_chat_store: ChatStore | None = None


def init_store(root) -> None:
    global _store
    _store = KBStore(root)


def get_store() -> KBStore:
    if _store is None:
        raise RuntimeError("kb store not initialized — call init_store() first")
    return _store


def init_chat_store(root) -> None:
    global _chat_store
    _chat_store = ChatStore(root)


def get_chat_store() -> ChatStore:
    if _chat_store is None:
        raise RuntimeError("chat store not initialized — call init_chat_store() first")
    return _chat_store


@router.get("/folders")
def list_folders() -> list[str]:
    return get_store().list_folders()


@router.get("/entries")
def list_entries(folder: str) -> list[str]:
    """`folder` is a query param, not a path segment — nested paths like
    "Personal Development/Physical/Fitness" contain slashes that don't
    survive as a single {folder} path parameter."""
    return get_store().list_entries(folder)


@router.get("/files")
def list_files(folder: str) -> list[str]:
    """Raw files directly under `folder` that aren't KB entries — e.g. an
    assets/ directory's actual photos/PDFs, which /entries can't see."""
    return get_store().list_files(folder)


@router.get("/entry")
def read_entry(folder: str, slug: str) -> dict:
    """Body + the freeform `fields` (unchanged), plus everything else in the
    entry's frontmatter (`meta`) and its frontmatter photo list (`assets`) so
    structured entries — wardrobe, documents, home items... — render fully."""
    entry = get_store().read_full(folder, slug)
    if entry is None:
        raise HTTPException(404, "entry not found")
    return entry


@router.get("/entries-meta")
def list_entries_meta(folder: str) -> list[dict]:
    """Every entry in a folder with its metadata + thumbnails' asset paths in
    one call — feeds the gallery / cards / table layouts."""
    return get_store().list_entries_meta(folder)


@router.get("/view")
def get_view(folder: str) -> dict:
    """A folder's layout: the saved _view.json if there is one, otherwise a
    sensible default inferred from what's in the folder."""
    saved = get_store().read_view(folder)
    if saved is not None:
        try:
            return {**ViewConfig(**saved).model_dump(), "source": "saved"}
        except ValueError:
            pass  # invalid saved config -> fall through to inference
    inferred = infer_view(get_store().list_entries_meta(folder))
    return {**inferred.model_dump(), "source": "inferred"}


@router.put("/view")
def put_view(folder: str, body: ViewConfig) -> dict:
    get_store().write_view(folder, body.model_dump())
    return {**body.model_dump(), "source": "saved"}


@router.get("/search")
def search_entries(q: str) -> list[dict]:
    """Search every entry in the KB by filename and body content, regardless
    of which folder it's filed under — lets Browse jump straight to a note
    instead of clicking through the folder tree to find it."""
    return get_store().search(q)


@router.post("/sort")
def sort_entry(
    content: str = Body(..., media_type="text/plain"),
    target_folder: str | None = None,
    target_slug: str | None = None,
) -> dict:
    """Proposes a folder/title/content — never writes anything.
    - No target: proposes a brand new entry anywhere, folder AI-guessed.
    - target_folder + target_slug: reads that existing file and proposes a
      merged update to it instead of creating a new one.
    - target_folder alone: a folder-scoped chat/drop — folder is FIXED (not
      guessed), only title/content get proposed. Used by the per-folder chat
      so everything it creates stays under the folder it's scoped to.
    Either way, POST /kb/entries is the separate, explicit commit step (see
    Approval before write)."""
    if target_folder and target_slug:
        existing = get_store().read(target_folder, target_slug)
        if existing is None:
            raise HTTPException(404, "target entry not found")
        first_line, _, rest = existing.partition("\n")
        title = first_line.lstrip("# ").strip() or target_slug
        merged_body = suggest_kb_update(rest.lstrip("\n"), content)
        return {"folder": target_folder, "title": title, "content": merged_body}

    if target_folder:
        scoped = suggest_kb_entry_for_folder(content, get_store().notes_index())
        return {"folder": target_folder, **scoped.model_dump()}

    suggestion = suggest_kb_entry(content, get_store().list_folders(), get_store().notes_index())
    return suggestion.model_dump()


class EntryCreate(BaseModel):
    folder: str
    title: str
    content: str
    links: list[str] | None = None
    fields: dict[str, str] | None = None


@router.post("/entries")
def create_entry(body: EntryCreate) -> dict:
    content = _localize_remote_images(body.content, body.folder, get_store())
    folder_slug, entry_slug = get_store().write(body.folder, body.title, content, body.links, fields=body.fields)
    return {"folder": folder_slug, "slug": entry_slug}


@router.get("/asset")
def get_asset(folder: str, path: str) -> Response:
    data = get_store().read_asset(folder, path)
    if data is None:
        raise HTTPException(404, "asset not found")
    mime_type, _ = mimetypes.guess_type(path)
    return Response(content=data, media_type=mime_type or "application/octet-stream")


@router.post("/entry/asset")
async def add_entry_asset(folder: str = Form(...), slug: str = Form(...), file: UploadFile = File(...)) -> dict:
    """Attaches a new file (any type — photo, video, STL, PDF, docx,
    spreadsheet) to an entry that already exists, from the generic page
    builder — as opposed to /entries/with-asset, which only attaches at
    creation time."""
    data = await file.read()
    try:
        asset_path = get_store().add_asset_to_entry(folder, slug, file.filename or "asset", data)
    except FileNotFoundError:
        raise HTTPException(404, "entry not found")
    return {"folder": folder, "slug": slug, "asset": asset_path}


@router.post("/asset/replace")
async def replace_asset(folder: str = Form(...), path: str = Form(...), file: UploadFile = File(...)) -> dict:
    """Overwrites an existing asset IN PLACE at the same path — "I edited
    this file elsewhere, here's the new version" — rather than creating a
    new entry. The markdown's [asset](...) link never changes."""
    data = await file.read()
    try:
        get_store().replace_asset(folder, path, data)
    except FileNotFoundError:
        raise HTTPException(404, "asset folder not found")
    return {"folder": folder, "path": path}


@router.get("/asset/spreadsheet")
def get_spreadsheet(folder: str, path: str) -> dict:
    data = get_store().read_asset(folder, path)
    if data is None:
        raise HTTPException(404, "asset not found")
    try:
        return read_spreadsheet(data)
    except Exception:
        raise HTTPException(400, "couldn't read this as a spreadsheet")


class SpreadsheetSave(BaseModel):
    sheets: list[dict]


@router.put("/asset/spreadsheet")
def save_spreadsheet(folder: str, path: str, body: SpreadsheetSave) -> dict:
    data = write_spreadsheet(body.sheets)
    try:
        get_store().replace_asset(folder, path, data)
    except FileNotFoundError:
        raise HTTPException(404, "asset folder not found")
    return {"folder": folder, "path": path}


@router.get("/photos")
def list_photos() -> list[dict]:
    """Every KB entry filed under Media/Photos, with all its assets — the
    Gallery page's data source. Same EXIF-based placement compute_photo_folder()
    already does on drop; this just surfaces what landed there as a grid."""
    store = get_store()
    results = []
    for folder in store.list_folders():
        if folder != "media/photos" and not folder.startswith("media/photos/"):
            continue
        for slug in store.list_entries(folder):
            content = store.read(folder, slug)
            if not content:
                continue
            assets = _ASSET_LINES_RE.findall(content)
            if not assets:
                continue
            title = content.split("\n", 1)[0].lstrip("# ").strip() or slug
            results.append({"folder": folder, "slug": slug, "title": title, "assets": assets})
    return results


@router.post("/drop")
async def drop_file(file: UploadFile = File(...), description: str = Form("")) -> dict:
    """Proposes a folder/title/content for an uploaded photo/PDF/DOCX/STL —
    never writes anything, same Approval-before-write contract as /kb/sort.
    The frontend holds onto the file and re-sends it to /kb/entries/with-asset
    to actually commit, mirroring how /kb/sort + /kb/entries already split
    propose from write for plain text."""
    data = await file.read()
    description_text = describe_drop(file.filename or "upload", data, description)
    suggestion = suggest_kb_entry(description_text, get_store().list_folders(), get_store().notes_index())
    return suggestion.model_dump()


@router.post("/batch-drop")
async def batch_drop(
    files: list[UploadFile] = File(...),
    manual_date: date | None = Form(None),
    manual_trip_name: str = Form(""),
) -> dict:
    """Multi-file import: extracts every file the same way /kb/drop does, then
    ONE AI call sees them all together and proposes folder/title/content per
    file — grouped into "buckets" by shared folder so related files land
    together instead of drifting into near-duplicate folders. Never writes;
    the frontend reviews (accept a whole bucket, edit one file, reassign it
    elsewhere) then commits each file individually via /kb/entries/with-asset.

    manual_date/manual_trip_name are the fallback for photos with no EXIF at
    all (screenshots, anything re-shared through an app that strips it) —
    when given, they apply to every image in this drop and take priority over
    whatever EXIF says (you know your own trip better than a camera clock)."""
    # Opaque file_id, not the real filename, is what's sent to/from the AI —
    # a model asked to echo back something that looks like a filename will
    # happily "improve" it instead (this broke real filename correlation on
    # first pass), but reliably echoes an opaque token unchanged.
    entries = []
    filenames_by_id: dict[str, str] = {}
    journal_dates_by_id: dict[str, str] = {}
    photo_dates_by_id: dict[str, object] = {}
    locations_by_id: dict[str, dict] = {}
    for i, f in enumerate(files):
        file_id = f"file_{i}"
        data = await f.read()
        description = describe_drop(f.filename or "upload", data, "")
        entries.append({"file_id": file_id, "description": description})
        filenames_by_id[file_id] = f.filename or "upload"
        if not is_image(f.filename or ""):
            continue  # manual date/trip only ever apply to actual photos
        # Deterministic, no AI: a photo's own EXIF date/GPS. The date, matched
        # against days you've actually journaled, connects trip photos to
        # that day's entry; the date+location (+ any AI-recognized trip_name
        # below) together decide where the actual photo FILE gets saved —
        # Media/Photos/<Year>/<Month>/<trip, or country/state/city, or
        # nothing> — real folders, not just a graph edge. manual_date fills
        # in for/overrides EXIF; location still comes from EXIF regardless
        # (there's no manual GPS input — just pick a trip name instead).
        photo_date = manual_date or extract_photo_date(data)
        if photo_date is not None:
            photo_dates_by_id[file_id] = photo_date
            if get_journal_store().load(photo_date) is not None:
                journal_dates_by_id[file_id] = photo_date.isoformat()
            location = extract_photo_location(data)
            if location is not None:
                locations_by_id[file_id] = location

    suggestion = suggest_kb_batch(entries, get_store().list_folders(), get_store().notes_index())

    buckets: dict[str, list[dict]] = {}
    for file_suggestion in suggestion.files:
        filename = filenames_by_id.get(file_suggestion.file_id)
        if filename is None:
            continue  # model returned an id that wasn't given — drop rather than mis-attribute
        links = list(file_suggestion.links)
        journal_date = journal_dates_by_id.get(file_suggestion.file_id)
        if journal_date and journal_date not in links:
            links.append(journal_date)

        photo_date = photo_dates_by_id.get(file_suggestion.file_id)
        trip_name = manual_trip_name.strip() or file_suggestion.trip_name or None
        folder = (
            compute_photo_folder(
                photo_date, locations_by_id.get(file_suggestion.file_id), trip_name, get_profile_store().load().home_countries
            )
            if photo_date is not None
            else file_suggestion.folder
        )
        buckets.setdefault(folder, []).append(
            {"filename": filename, "title": file_suggestion.title, "content": file_suggestion.content, "links": links}
        )
    return {"buckets": [{"folder": folder, "files": files} for folder, files in buckets.items()]}


@router.post("/entries/with-asset")
async def create_entry_with_asset(
    folder: str = Form(...),
    title: str = Form(...),
    content: str = Form(...),
    files: list[UploadFile] = File(...),  # as many as you want — one [asset](...) line per file
    links: str = Form(""),  # comma-separated — multipart forms don't carry real arrays cleanly
) -> dict:
    file_data = [(f.filename or "asset", await f.read()) for f in files]
    link_list = [l.strip() for l in links.split(",") if l.strip()]
    # Deterministic EXIF GPS off the first photo, if present — no AI, no user input
    location = extract_photo_location(file_data[0][1]) if file_data else None
    content = _localize_remote_images(content, folder, get_store())
    folder_slug, entry_slug = get_store().write(folder, title, content, link_list, location)
    asset_paths = [get_store().save_asset(folder_slug, name, data) for name, data in file_data]
    # Re-write with the asset reference(s) now that we know their final
    # path(s) — write() needs to happen first so folder_slug/entry_slug are
    # resolved. One [asset](...) line per photo — graph_entries()/the
    # browse page both read every trailing line, not just the last.
    asset_lines = "\n".join(f"[asset]({p})" for p in asset_paths)
    linked_content = f"{content}\n\n{asset_lines}" if asset_lines else content
    get_store().write(folder, title, linked_content, link_list, location)
    return {"folder": folder_slug, "slug": entry_slug, "assets": asset_paths, "location": location}


@router.get("/graph")
def kb_graph() -> dict:
    """Every relationship the graph view can show: note-to-note links (AI
    proposed, frontmatter — never touches note bodies), note-to-asset, plus
    whatever's already structurally connected elsewhere in the app (meals to
    their ingredients, routines to their exercises, outfits to their items) —
    pulled in by the caller, this endpoint only owns the KB-note half."""
    return {"notes": get_store().graph_entries()}


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    # A plain string for a normal turn, or Anthropic-style content blocks
    # (text/image/document) when a photo or PDF was attached — passed
    # straight through to the API as-is (see run_kb_chat). ChatStore.save()
    # collapses the block form to plain text before persisting; a live
    # attachment is context for THIS answer, not something the scratch chat
    # store should hold onto as raw base64 forever.
    content: str | list[dict]


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    use_kb: bool = True
    research: bool = False
    folder: str | None = None  # scoped chat — context limited to this folder + its subfolders
    model: str | None = None  # the picker's choice (see CHAT_MODELS); None = the old default/research behavior


@router.get("/models")
def list_chat_models() -> list[dict]:
    return CHAT_MODELS


@router.post("/chat")
def chat_endpoint(body: ChatRequest) -> dict:
    try:
        reply = run_kb_chat(
            get_store(), [m.model_dump() for m in body.messages], body.use_kb, body.research, body.folder, body.model
        )
    except UnknownModelError as e:
        raise HTTPException(400, str(e))
    except OpenAIError as e:
        # Missing key vs. a real API error read differently to the user.
        if "api_key" in str(e) or "credentials" in str(e):
            raise HTTPException(400, "OPENAI_API_KEY not set — add it to core/.env to use GPT models")
        raise HTTPException(502, f"OpenAI error: {e}")
    return {"reply": reply}


class GenerateImageRequest(BaseModel):
    prompt: str


@router.post("/generate-image")
def generate_image_endpoint(body: GenerateImageRequest) -> dict:
    """Never writes — returns the image for the frontend to preview and,
    same as any other drop, push through the existing /kb/entries/with-asset
    path once reviewed (Approval before write)."""
    try:
        data = generate_image(body.prompt)
    except OpenAIError:
        raise HTTPException(400, "OPENAI_API_KEY not set — add it to core/.env to use image generation")
    return {"data": base64.b64encode(data).decode(), "mime_type": "image/png"}


@router.get("/chats")
def list_chats() -> list[dict]:
    return get_chat_store().list_sessions()


@router.post("/chats")
def create_chat(title: str = Body("", embed=True)) -> dict:
    return {"id": get_chat_store().create(title)}


@router.get("/chats/{session_id}")
def load_chat(session_id: str) -> list[dict]:
    return get_chat_store().load(session_id)


class SaveChatRequest(BaseModel):
    title: str = ""
    messages: list[ChatMessage]


@router.put("/chats/{session_id}")
def save_chat(session_id: str, body: SaveChatRequest) -> dict:
    get_chat_store().save(session_id, body.title, [m.model_dump() for m in body.messages])
    return {"id": session_id}


@router.delete("/chats/{session_id}")
def delete_chat(session_id: str) -> dict:
    get_chat_store().delete(session_id)
    return {"deleted": session_id}
