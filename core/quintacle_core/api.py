from __future__ import annotations

import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

# Loads core/.env (ANTHROPIC_API_KEY, etc.) before anything reads os.environ.
load_dotenv()

from . import clock
from . import db
from .day_bundle import build_day_bundle
from .graph import get_graph_store, init_graph_store, sync_frontmatter_links
from .nodes.drop_router import (
    IMAGE_MIME_TYPES,
    classify_image_type,
    classify_text_file_type,
    entry_type_for_image_kind,
    extension,
    extract_finance_from_receipt,
    parse_prefix,
    parse_routine_definition,
)
from .nodes.journal.llm import parse_journal_dump
from .nodes.journal.normalize import canonicalize_entries, canonicalize_name
from .nodes.kb.drop import describe_drop, extract_photo_date, extract_photo_location
from .nodes.kb.photo_organizer import compute_photo_folder
from .nodes.kb.llm import suggest_kb_entry, suggest_kb_placement
from .nodes.logs.meal_composer import resolve_composition, suggest_meal_composition
from .nodes.logs.nutrition_llm import estimate_nutrition, estimate_nutrition_from_image
from .nodes.schedule.api import init_store as init_schedule_store, get_store as get_schedule_store, router as schedule_router
from .nodes.logs.api import init_repo, init_profile_ref, get_repo as get_logs_repo, get_log_store, router as logs_router
from .nodes.logs.log_store import LogFileStore
from .nodes.journal.api import init_store as init_journal_store, get_store as get_journal_store, router as journal_router
from .nodes.kb.api import init_store as init_kb_store, init_chat_store, get_store as get_kb_store, router as kb_router
from .nodes.profile.api import init_store as init_profile_store, router as profile_router
from .nodes.wardrobe.api import (
    init_store as init_wardrobe_store,
    get_item_store as get_wardrobe_item_store,
    get_outfit_store as get_wardrobe_outfit_store,
    router as wardrobe_router,
)
from .nodes.wardrobe.llm import (
    describe_outfit_photo,
    describe_wardrobe_item,
    describe_wardrobe_item_from_text,
    resolve_outfit,
    suggest_outfit,
)
from .nodes.grooming.api import (
    init_store as init_grooming_store,
    get_item_store as get_grooming_item_store,
    get_routine_store as get_grooming_routine_store,
    router as grooming_router,
)
from .nodes.grooming.llm import (
    describe_grooming_item,
    describe_grooming_item_from_text,
    resolve_grooming_routine,
    suggest_grooming_routine,
)
from .nodes.documents.api import init_store as init_document_store, get_store as get_document_store, router as document_router
from .nodes.documents.llm import structure_document
from .nodes.home.api import (
    init_store as init_home_store,
    get_residence_store,
    resolve_residence,
    router as home_router,
)
from .nodes.home.llm import structure_home_item, structure_residence
from .nodes.travel.api import init_store as init_travel_store, get_store as get_travel_store, router as travel_router
from .nodes.travel.llm import maybe_structure_experience, structure_experience
from .nodes.people.api import init_store as init_people_store, get_store as get_people_store, router as people_router
from .nodes.people.llm import maybe_structure_person_mention, structure_person
from .nodes.finance.api import init_store as init_credit_card_store, router as credit_card_router, investments_router, get_investment_store
from .nodes.finance.llm import structure_credit_card, structure_investment
from .nodes.vault.api import init_store as init_vault_store, router as vault_router
from .sync import init_sync, router as sync_router

DATA_DIR = Path(os.environ.get("QUINTACLE_DATA_DIR", Path.home() / ".quintacle"))


def create_app() -> FastAPI:
    app = FastAPI(title="Quintacle Core")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    init_schedule_store(DATA_DIR / "schedule" / "todos")
    app.include_router(schedule_router)

    # Logs write through into the same kb/ tree KBStore uses — dense daily
    # logs live nested inside the relevant KB pillar folder (e.g.
    # Personal Development/Physical/Fitness/logs/), so copying that folder
    # out on its own carries both the reference notes and the real numbers.
    kb_root = DATA_DIR / "kb"
    conn = db.connect(DATA_DIR / "quintacle.db")
    init_graph_store(DATA_DIR, conn)
    init_repo(conn, LogFileStore(kb_root))
    app.include_router(logs_router)

    init_journal_store(DATA_DIR / "journal")
    app.include_router(journal_router)

    init_kb_store(kb_root)
    init_chat_store(DATA_DIR / "kb_chats")
    app.include_router(kb_router)

    profile_store = init_profile_store(DATA_DIR / "profile.json")
    init_profile_ref(profile_store)
    app.include_router(profile_router)

    init_wardrobe_store(kb_root)
    app.include_router(wardrobe_router)

    init_grooming_store(kb_root)
    app.include_router(grooming_router)

    init_document_store(kb_root, get_schedule_store)
    app.include_router(document_router)

    init_home_store(kb_root)
    app.include_router(home_router)

    init_travel_store(kb_root)
    app.include_router(travel_router)

    init_people_store(kb_root)
    app.include_router(people_router)

    init_credit_card_store(kb_root)
    app.include_router(credit_card_router)
    app.include_router(investments_router)

    # Deliberately OUTSIDE kb_root — every model-facing surface (KB chat,
    # MCP tools, search, graph, drop) only walks kb/, so vault/ being a
    # sibling directory is what keeps secrets structurally unreachable.
    init_vault_store(DATA_DIR / "vault")
    app.include_router(vault_router)

    # Manual LAN sync (sync.py) — must come after the logs/graph inits above,
    # since a pull rebuilds those stores' SQLite indexes when it finishes.
    init_sync(DATA_DIR)
    app.include_router(sync_router)

    # One-time per-process catch-up: materializes every pre-existing note's
    # and experience's frontmatter `links` into the edges table (see
    # graph.py / docs/graph-model.md), so switching /graph over to reading
    # SQLite doesn't silently blank out connections that existed before this
    # table did. Cheap at current scale — one pass over the KB at startup,
    # not on every request. Not the same thing as graph.rebuild_from_folder
    # (that recovers SQLite from already-materialized edge files; this reads
    # frontmatter, the thing that hasn't been materialized yet at all).
    notes = get_kb_store().graph_entries()
    experiences = get_travel_store().all()
    note_id_by_title = {n["title"]: f"note:{n['folder']}/{n['slug']}" for n in notes}
    journal_id_by_date = {d.isoformat(): f"journal:{d.isoformat()}" for d in get_journal_store().list_dates()}
    experience_id_by_name = {e["name"]: f"experience:{e['folder']}/{e['slug']}" for e in experiences}
    link_target_by_title = {**note_id_by_title, **journal_id_by_date, **experience_id_by_name}
    title_lookup = list(link_target_by_title.keys())
    for n in notes:
        note_id = f"note:{n['folder']}/{n['slug']}"
        resolved = [canonicalize_name(t, title_lookup) for t in n["links"]]
        sync_frontmatter_links(note_id, resolved, link_target_by_title)
    for e in experiences:
        exp_id = f"experience:{e['folder']}/{e['slug']}"
        resolved = [canonicalize_name(t, title_lookup) for t in (e.get("links") or [])]
        sync_frontmatter_links(exp_id, resolved, link_target_by_title)

    @app.get("/day/counts")
    def day_counts(start: date, end: date) -> dict[str, int]:
        """date -> total logged-entry count across activities/food/exercise/substances,
        for calendar month-view badges."""
        repo = get_logs_repo()
        counts: dict[str, int] = {}
        for rows in (
            repo.activities_between(start, end),
            repo.food_log_between(start, end),
            repo.exercise_between(start, end),
            repo.substances_between(start, end),
            repo.expenses_between(start, end),
        ):
            for row in rows:
                counts[row["date"]] = counts.get(row["date"], 0) + 1
        # Completed todos count as actions on the day they were finished —
        # the whole point of completed_at (see schedule/models.py).
        for t in get_schedule_store().list():
            if t.done and t.completed_at and start <= t.completed_at.date() <= end:
                key = t.completed_at.date().isoformat()
                counts[key] = counts.get(key, 0) + 1
        return counts

    @app.get("/day/{for_date}")
    def day_detail(for_date: date) -> dict:
        """Calendar B: what actually happened on a given date, pulled deterministically
        from every node that touches it — architecture.md's March-13 example, generalized.
        Includes `photos`: the KB notes linked to this day via the edges table (a photo's
        EXIF date -> `on_day` edge), each with its stored drop-time description and asset
        paths. Shared assembly with the MCP `day_recall` tool — see day_bundle.py."""
        return build_day_bundle(
            for_date,
            journal_store=get_journal_store(),
            todo_store=get_schedule_store(),
            logs_repo=get_logs_repo(),
            kb_store=get_kb_store(),
            edges_conn=get_graph_store().conn,
        )

    @app.post("/drop")
    async def propose_drop(
        text: str = Form(""),
        file: UploadFile | None = File(None),
        file2: UploadFile | None = File(None),
        keep_as_is: bool = Form(False),
        reference_date: str = Form(""),
    ) -> dict:
        """The one general drop, covering schedule/journal/finance/KB entries.
        Deterministic keyword-prefix routing first (parse_prefix — no AI call);
        an unprefixed photo gets one cheap vision classification call to decide
        its kind; everything else falls through to full AI classification.
        Never writes — the frontend reviews/edits, then commits through each
        type's existing endpoint (Approval before write). keep_as_is applies to
        an already-finished document (an itinerary, a report) — AI only
        suggests where it goes, never rewrites the content. file2 is an
        optional second photo — the back of something, a label, another
        angle — read together with file as ONE thing, not a second entry."""
        if not text.strip() and file is None:
            raise HTTPException(400, "nothing to drop — provide text and/or a file")

        data = await file.read() if file is not None else None
        filename = file.filename if (file is not None and file.filename) else ""
        ext = extension(filename) if filename else ""
        is_image = data is not None and ext in IMAGE_MIME_TYPES
        mime = IMAGE_MIME_TYPES.get(ext) if is_image else None

        data2 = await file2.read() if file2 is not None else None
        filename2 = file2.filename if (file2 is not None and file2.filename) else ""
        ext2 = extension(filename2) if filename2 else ""
        is_image2 = data2 is not None and ext2 in IMAGE_MIME_TYPES
        mime2 = IMAGE_MIME_TYPES.get(ext2) if is_image2 else None
        # The multi-image vision helpers all take this shape — built once,
        # reused by whichever branch below needs it.
        photos: list[tuple[bytes, str]] = ([(data, mime)] if is_image else []) + ([(data2, mime2)] if is_image2 else [])

        prefix = parse_prefix(text) if text.strip() else None
        entry_type, rest = prefix if prefix else (None, text)

        # Computed once, reused by whichever branch below needs a text
        # description AND by the additive Experience check after the branch
        # — avoids duplicate vision/PDF/DOCX extraction calls for the same file.
        _description: str | None = None

        def get_description() -> str:
            nonlocal _description
            if _description is None:
                _description = describe_drop(filename, data, rest, filename2, data2) if data is not None else rest
            return _description

        if entry_type is None:
            if is_image:
                entry_type = entry_type_for_image_kind(classify_image_type(data, mime))
            elif data is not None:
                # PDF/DOCX/STL etc — no vision call available, so classify off
                # the extracted text instead: a formal document (ID, visa,
                # lease...) routes into the real Document Vault (structured
                # fields, auto-renewal-todo); anything else stays a KB note.
                entry_type = classify_text_file_type(get_description())

        # The date "yesterday"/"last Tuesday" resolve against — the day the
        # user picked in the UI (backfilling an older day), else today. Same
        # behavior Journal's /parse has always had via its for_date.
        try:
            reference_date = date.fromisoformat(reference_date) if reference_date else clock.today()
        except ValueError:
            raise HTTPException(400, "reference_date must be YYYY-MM-DD")
        known_meals = [dict(row) for row in get_logs_repo().list_meals()]
        known_routines = get_logs_repo().list_routines()

        # What text the Experience check (below, after the branch) should
        # look at — defaults to the raw text, overridden per-branch when a
        # richer extracted description already exists.
        experience_check_text: str | None = rest

        if entry_type == "workout_routine":
            parsed_routine = parse_routine_definition(rest)
            if parsed_routine is not None:
                name, exercises = parsed_routine
                known_names = [r["name"] for r in known_routines]
                known_exercises = sorted({e["exercise_name"] for e in (get_log_store().all_entries("exercise") if get_log_store() else [])})
                entries = [
                    {
                        "type": "workout_routine",
                        "name": canonicalize_name(name, known_names),
                        "exercises": [canonicalize_name(e, known_exercises) for e in exercises],
                    }
                ]
            else:
                entries = [{"type": "workout_routine", "name": rest.strip()[:60] or "New routine", "exercises": []}]
        elif entry_type == "wardrobe_item":
            known_item_names = [i["name"] for i in get_wardrobe_item_store().all()]
            estimate = describe_wardrobe_item(photos, rest) if is_image else describe_wardrobe_item_from_text(rest)
            fields = estimate.model_dump()
            fields["suggested_name"] = canonicalize_name(fields["suggested_name"], known_item_names)
            entries = [{"type": "wardrobe_item", **fields}]
            experience_check_text = f"{fields['suggested_name']} {fields['description']} {rest}"
        elif entry_type == "outfit_composition":
            known_items = get_wardrobe_item_store().all()
            suggestion = suggest_outfit(rest, known_items)
            resolved = resolve_outfit(suggestion, known_items)
            entries = [{"type": "outfit_composition", **resolved}]
        elif entry_type == "outfit_photo":
            # A full look worn in one photo (a mirror selfie) — saved AS IS,
            # not decomposed into matched wardrobe items first.
            estimate = describe_outfit_photo(photos, rest)
            entries = [{"type": "outfit_photo", **estimate.model_dump()}]
            experience_check_text = f"{estimate.suggested_name} {estimate.description} {rest}"
        elif entry_type == "grooming_item":
            known_item_names = [i["name"] for i in get_grooming_item_store().all()]
            estimate = describe_grooming_item(photos, rest) if is_image else describe_grooming_item_from_text(rest)
            fields = estimate.model_dump()
            fields["suggested_name"] = canonicalize_name(fields["suggested_name"], known_item_names)
            entries = [{"type": "grooming_item", **fields}]
            experience_check_text = f"{fields['suggested_name']} {fields['description']} {rest}"
        elif entry_type == "grooming_routine_composition":
            known_items = get_grooming_item_store().all()
            suggestion = suggest_grooming_routine(rest, known_items)
            resolved = resolve_grooming_routine(suggestion, known_items)
            entries = [{"type": "grooming_routine_composition", **resolved}]
        elif entry_type == "document_entry":
            estimate = structure_document(get_description())
            entries = [{"type": "document_entry", **estimate.model_dump()}]
            experience_check_text = get_description()
        elif entry_type == "home_item":
            known_residence_names = [r["name"] for r in get_residence_store().all()]
            estimate = structure_home_item(get_description(), known_residence_names)
            fields = estimate.model_dump()
            # Deterministic resolution, no AI: an explicitly-named residence
            # fuzzy-matches the real list; otherwise falls back to whichever
            # residence has no moved_out date (your current home).
            residence = resolve_residence(fields.get("residence_name") or "")
            fields["residence_name"] = residence["name"] if residence else None
            entries = [{"type": "home_item", **fields}]
            experience_check_text = get_description()
        elif entry_type == "residence_entry":
            estimate = structure_residence(get_description())
            entries = [{"type": "residence_entry", **estimate.model_dump()}]
            experience_check_text = None  # a residence record itself isn't a visit-worthy "experience"
        elif entry_type == "experience_entry":
            # Explicit "experience:"/"visit:" prefix — intent already stated,
            # so no relevance gate, always extract fields.
            estimate = structure_experience(get_description())
            entries = [{"type": "experience_entry", **estimate.model_dump(exclude={"is_experience"})}]
            experience_check_text = None  # already is one, don't also run the additive check on itself
        elif entry_type == "person_entry":
            # Explicit "person:"/"friend:" prefix — intent already stated, so
            # no relevance gate, always extract fields. experience_check_text
            # stays populated (not nulled) — "first date with Sarah at a wine
            # bar" is BOTH a new person AND a venue worth its own Experience.
            estimate = structure_person(get_description(), reference_date)
            known_people = [p["name"] for p in get_people_store().all()]
            fields = estimate.model_dump()
            fields["suggested_name"] = canonicalize_name(fields["suggested_name"], known_people)
            entries = [{"type": "person_entry", **fields}]
            experience_check_text = get_description()
        elif entry_type == "credit_card_entry":
            # Explicit "creditcard:"/"card:" prefix — a card isn't a place or
            # a person, so no additive Experience/Person check needed.
            estimate = structure_credit_card(get_description())
            entries = [{"type": "credit_card_entry", **estimate.model_dump()}]
            experience_check_text = None
        elif entry_type == "investment_entry":
            # Explicit "invest:"/"stock:" prefix — a holding isn't a place or
            # a person, so no additive Experience/Person check needed.
            estimate = structure_investment(get_description())
            entries = [{"type": "investment_entry", **estimate.model_dump()}]
            experience_check_text = None
        elif entry_type == "ingredient_preset":
            known_ingredient_names = [i["name"] for i in get_logs_repo().list_ingredients()]
            if is_image:
                estimate = estimate_nutrition_from_image(photos, rest)
                fields = estimate.model_dump()
            else:
                estimate = estimate_nutrition(rest)
                fields = {"suggested_name": rest.strip()[:60] or "New ingredient", **estimate.model_dump()}
            # Same fuzzy-match safety net as exercise/substance names — a
            # second "Lamb" photo should update the existing preset, not fork
            # a near-duplicate because the model phrased the name slightly differently.
            fields["suggested_name"] = canonicalize_name(fields["suggested_name"], known_ingredient_names)
            entries = [{"type": "ingredient_preset", **fields}]
            experience_check_text = f"{fields.get('suggested_name', '')} {rest}"
        elif entry_type == "meal_composition":
            known_ingredients = [dict(row) for row in get_logs_repo().list_ingredients()]
            suggestion = suggest_meal_composition(rest, known_ingredients)
            resolved = resolve_composition(suggestion, known_ingredients)
            entries = [{"type": "meal_composition", **resolved}]
        elif entry_type == "finance" and is_image:
            entries = [extract_finance_from_receipt(photos, rest).model_dump()]
            experience_check_text = f"{entries[0].get('merchant', '')} {entries[0].get('category', '')} {rest}"
        elif entry_type == "kb_entry":
            description = get_description()
            existing_notes = get_kb_store().notes_index()
            # A real camera photo (has EXIF date) overrides wherever AI would
            # have filed it — goes to Media/Photos/<Year>/<Month>/... instead,
            # same deterministic date/geo placement batch-drop uses.
            photo_date = extract_photo_date(data) if is_image else None
            photo_location = extract_photo_location(data) if is_image and photo_date is not None else None
            journal_link = (
                [photo_date.isoformat()]
                if photo_date is not None and get_journal_store().load(photo_date) is not None
                else []
            )
            home_countries = profile_store.load().home_countries
            if keep_as_is:
                placement = suggest_kb_placement(description, get_kb_store().list_folders(), existing_notes)
                entries = [
                    {
                        "type": "kb_entry",
                        "folder": (
                            compute_photo_folder(photo_date, photo_location, None, home_countries)
                            if photo_date
                            else placement.folder
                        ),
                        "title": placement.title,
                        "content": description,
                        "links": list({*placement.links, *journal_link}),
                    }
                ]
            else:
                suggestion = suggest_kb_entry(description, get_kb_store().list_folders(), existing_notes)
                folder = (
                    compute_photo_folder(photo_date, photo_location, None, home_countries)
                    if photo_date
                    else suggestion.folder
                )
                links = list({*suggestion.links, *journal_link})
                entries = [{"type": "kb_entry", **{**suggestion.model_dump(), "folder": folder, "links": links}}]
            experience_check_text = description
        elif entry_type is not None:
            # todo / food / exercise / substance / activity / body_stat / finance(text)
            # — type already fixed deterministically; AI only extracts fields.
            parsed = parse_journal_dump(rest, known_meals, reference_date, forced_type=entry_type, known_routines=known_routines)
            entries = [e.model_dump() for e in parsed]
        else:
            # No prefix, no file — plain text with no deterministic signal at
            # all. Only path that hits full multi-type AI classification.
            parsed = parse_journal_dump(rest, known_meals, reference_date, known_routines=known_routines)
            entries = [e.model_dump() for e in parsed]

        # Propose-everything-plausible, prune-what-you-don't-want: independent
        # of whatever got classified above, also check whether this drop
        # describes a place/visit worth its own Experience record — cheap
        # (regex-gated, see travel/llm.py) and additive, not a replacement
        # for the primary classification. Matches the explicit "AI proposes
        # all of them, I prune" preference used for food+finance+experience too.
        # Pre-declared so the person-mention section below can check "did an
        # experience also get detected from this same drop" even when it
        # didn't (experience_check_text falsy, or not experience-worthy).
        exp_estimate = None
        if experience_check_text:
            exp_estimate = maybe_structure_experience(experience_check_text)
            if exp_estimate is not None:
                exp_links: list[str] = []
                if is_image and entry_type == "kb_entry":
                    # The kb_entry branch already proposed the photo's own
                    # note — link to whatever title it already has.
                    exp_links.append(entries[0]["title"])
                elif is_image:
                    # A real EXIF photo that did NOT already become its own
                    # kb_entry note (e.g. classified prepared_meal/wardrobe_item
                    # instead) still deserves a permanent home in the photo
                    # gallery — archive it independently so the experience has
                    # something real to link to, instead of being discarded.
                    photo_date = extract_photo_date(data)
                    if photo_date is not None:
                        photo_location = extract_photo_location(data)
                        existing_notes = get_kb_store().notes_index()
                        suggestion = suggest_kb_entry(get_description(), get_kb_store().list_folders(), existing_notes)
                        folder = compute_photo_folder(photo_date, photo_location, None, profile_store.load().home_countries)
                        journal_link = (
                            [photo_date.isoformat()] if get_journal_store().load(photo_date) is not None else []
                        )
                        photo_links = list({*suggestion.links, *journal_link})
                        entries.append(
                            {
                                "type": "kb_entry",
                                "folder": folder,
                                "title": suggestion.title,
                                "content": suggestion.content,
                                "links": photo_links,
                            }
                        )
                        exp_links.append(suggestion.title)
                entries.append(
                    {"type": "experience_entry", **exp_estimate.model_dump(exclude={"is_experience"}), "links": exp_links}
                )

        # Same additive philosophy, for people: does this ALSO say something
        # substantive about a specific person — new or already tracked? Falls
        # back to the raw text when experience_check_text was nulled out
        # (residence_entry) — still worth checking, e.g. "moved in with my
        # roommate Alex." Skipped entirely for person_entry's own branch, to
        # avoid proposing a duplicate of the very entry just built.
        person_check_text = experience_check_text if experience_check_text is not None else rest
        if person_check_text and entry_type != "person_entry":
            known_people = [p["name"] for p in get_people_store().all()]
            person_estimate = maybe_structure_person_mention(person_check_text, known_people, reference_date)
            if person_estimate is not None:
                if person_estimate.is_new_person:
                    entries.append(
                        {
                            "type": "person_entry",
                            "suggested_name": person_estimate.person_name,
                            "category": person_estimate.category,
                            "how_met": person_estimate.how_met,
                            "met_date": person_estimate.met_date,
                            "notes": person_estimate.notes,
                        }
                    )
                else:
                    matched_name = canonicalize_name(person_estimate.person_name, known_people)
                    resolved = get_people_store().find(matched_name)
                    if resolved is not None:
                        # An experience AND a known person detected from the
                        # SAME drop get cross-referenced by name here — the
                        # actual typed edge (kind="mentions_person") gets
                        # created at commit time by graph.link_new_entry
                        # (see travel/api.py's create_experience and
                        # kb/api.py's create_entry), once both sides have a
                        # real id to point at. These `links` hints are what
                        # makes that match deterministic instead of hoping
                        # the AI-written notes text happens to repeat the
                        # name/place verbatim.
                        if exp_estimate is not None:
                            exp_links.append(matched_name)
                        entries.append(
                            {
                                "type": "kb_entry",
                                "folder": f"{resolved['folder']}/Mentions",
                                "title": f"{matched_name} — {reference_date.isoformat()}",
                                "content": person_estimate.notes,
                                "links": [exp_estimate.suggested_name] if exp_estimate is not None else [],
                            }
                        )

        canonicalize_entries(entries, get_log_store())
        return {"entries": entries}

    @app.get("/graph")
    def graph() -> dict:
        """Everything connected to everything else, for the graph view:
        note-to-note links, note-to-asset from the KB, plus every
        relationship that already exists structurally elsewhere in the app
        (a meal's real ingredients, a routine's real exercises, an outfit's
        real items). Nothing here is a new kind of data — this just surfaces
        connections that already exist, in one shape a graph can render.

        Note/experience/person links used to be recomputed here on every
        request (walk every note's frontmatter, fuzzy-match every title) —
        see docs/graph-model.md's "graph engine plan". Those are now
        materialized at write time (graph.sync_frontmatter_links,
        graph.link_new_entry) into the `edges` SQLite table; this just reads
        it — an indexed query instead of an O(notes x links) walk."""
        nodes: list[dict] = []
        edges: list[dict] = []

        # Journal days are a real node type too — a photo's EXIF date gets
        # linked to the day it matches (see kb/api.py's batch_drop), so that
        # link needs somewhere to resolve to.
        for d in get_journal_store().list_dates():
            iso_date = d.isoformat()
            nodes.append({"id": f"journal:{iso_date}", "type": "journal_day", "label": iso_date})

        notes = get_kb_store().graph_entries()
        for n in notes:
            note_id = f"note:{n['folder']}/{n['slug']}"
            node = {"id": note_id, "type": "note", "label": n["title"], "folder": n["folder"], "slug": n["slug"]}
            if n.get("location"):
                node["location"] = n["location"]
            nodes.append(node)
            if n["asset"]:
                asset_id = f"asset:{n['folder']}/{n['slug']}"
                nodes.append({"id": asset_id, "type": "asset", "label": n["asset"], "folder": n["folder"], "path": n["asset"]})
                edges.append({"source": note_id, "target": asset_id, "kind": "has_asset"})

        for e in get_travel_store().all():
            exp_id = f"experience:{e['folder']}/{e['slug']}"
            nodes.append(
                {
                    "id": exp_id,
                    "type": "experience",
                    "label": e["name"],
                    "folder": e["folder"],
                    "slug": e["slug"],
                    "city": e.get("city"),
                    "kind": e.get("kind"),
                }
            )

        for edge in get_graph_store().all():
            edges.append({"source": edge["source_id"], "target": edge["target_id"], "kind": edge["kind"]})

        repo = get_logs_repo()
        ingredients_by_id = {i["id"]: i for i in repo.list_ingredients()}
        for ing in ingredients_by_id.values():
            nodes.append({"id": f"ingredient:{ing['id']}", "type": "ingredient", "label": ing["name"]})
        for meal in repo.list_meals():
            meal_id = f"meal:{meal['id']}"
            nodes.append({"id": meal_id, "type": "meal", "label": meal["name"]})
            for comp in repo.meal_components(meal["id"]):
                edges.append({"source": meal_id, "target": f"ingredient:{comp['ingredient_id']}", "kind": "made_of"})

        exercise_ids: set[str] = set()
        for routine in repo.list_routines():
            routine_id = f"routine:{routine['name']}"
            nodes.append({"id": routine_id, "type": "routine", "label": routine["name"]})
            for ex in routine.get("exercises", []):
                ex_id = f"exercise:{ex}"
                if ex_id not in exercise_ids:
                    exercise_ids.add(ex_id)
                    nodes.append({"id": ex_id, "type": "exercise", "label": ex})
                edges.append({"source": routine_id, "target": ex_id, "kind": "includes"})

        item_ids: set[str] = set()
        for item in get_wardrobe_item_store().all():
            item_id = f"item:{item['name']}"
            item_ids.add(item_id)
            nodes.append({"id": item_id, "type": "wardrobe_item", "label": item["name"]})
        for outfit in get_wardrobe_outfit_store().all():
            outfit_id = f"outfit:{outfit['name']}"
            nodes.append({"id": outfit_id, "type": "outfit", "label": outfit["name"]})
            for item_name in outfit.get("items", []):
                item_id = f"item:{item_name}"
                if item_id not in item_ids:
                    item_ids.add(item_id)
                    nodes.append({"id": item_id, "type": "wardrobe_item", "label": item_name})
                edges.append({"source": outfit_id, "target": item_id, "kind": "includes"})

        return {"nodes": nodes, "edges": edges}

    return app


app = create_app()
