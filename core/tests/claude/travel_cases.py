"""TRAVEL sorting + the PLACE GRAPH, written once and run by BOTH live suites
(each suite's test module binds `client` + `provider`). Like sort_cases.py,
every expectation is the RIGHT product answer fixed up front from intent; a
failure is a finding about the model/code, never a reason to re-fit it.

Relies on cases.seed: Fun/Travel/Planned/Japan, Fun/Travel/Experiences/Portugal
and Fun/Travel/Bucket List already exist in the sandbox (so the folder
suggester is grounded, per CLAUDE.md). Trip-plan PDF/MD, e-ticket and
passport sorting live in sort_cases.py and are NOT repeated here.

Code facts these checks are built on (read, not guessed):
- An unprefixed TYPED line goes through parse_journal_dump (its kb_entry
  type), a "note:" prefix or a dropped file goes through suggest_kb_entry,
  whose travel rule says someday-places -> "Fun/Travel/Bucket List" and
  future trips -> "Fun/Travel/Planned/<Region>", reusing an existing subfolder.
- Folders on disk are slugged per segment ("Bucket List" -> "bucket-list"),
  so a proposal's folder is compared slug-to-slug.
- A visit becomes an `experience_entry` proposal (api.py's additive check ->
  travel/llm.maybe_structure_experience): fields suggested_name, kind, city,
  rating, would_return, visited_date, notes, links.
- The place graph (place_graph.py) links a Fun/Travel/Planned/** note on save
  (POST /kb/entries -> link_note_places): `located_in` note -> city, then
  `part_of` city -> country -> continent, ids like place:europe/austria/vienna
  (or a real `note:places/...` note in place of the virtual city). GET /graph
  returns them as {"source","target","kind"} edges; POST
  /kb/graph/backfill-places?dry_run=false re-links every existing note.
"""
from quintacle_core.markdown_paths import slugify

from tests.claude.harness import drop, first, types

BUCKET_WISH = "Someday I want to see the northern lights in Tromsø, Norway"

KYOTO_TRIP = "Got back from Kyoto last week: Fushimi Inari at dawn, Arashiyama bamboo grove, kaiseki dinner"

# Deliberately never says "Japan": knowing Osaka/Nara are in the already-planned
# region is the whole point of reusing Fun/Travel/Planned/Japan.
OSAKA_PLAN = [
    "OSAKA + NARA PLAN | APRIL 2027",
    "5 days. Fly into Kansai (KIX) Sat Apr 10, out of KIX Thu Apr 15. Status: planning, nothing booked.",
    "Hotel idea: Cross Hotel Osaka (Shinsaibashi), 5 nights.",
    "Day 1 Osaka: Dotonbori food crawl, takoyaki, Hozenji Yokocho.",
    "Day 2 Osaka: Osaka Castle park, Umeda Sky Building at sunset.",
    "Day 3 Nara day trip: Nara Park deer, Todai-ji, Kasuga Taisha. Kintetsu line ~40 min.",
    "Day 4 Osaka: Kuromon market, Shinsekai, Tsutenkaku.",
    "Budget: about $1,800 excluding flights.",
]

VIENNA_PLAN = [
    "VIENNA, AUSTRIA | MAY 2027 | TRIP PLAN",
    "4 days in Vienna, one traveler. Fly IAD to Vienna (VIE) Fri May 14, back Tue May 18. Not booked yet.",
    "Hotel idea: Hotel Sacher or something near Stephansplatz, 4 nights.",
    "Day 1: Stephansdom, Graben, coffee and Sachertorte at Cafe Central.",
    "Day 2: Schonbrunn Palace and gardens, evening at the Musikverein.",
    "Day 3: Belvedere (Klimt's The Kiss), Naschmarkt lunch, Prater wheel.",
    "Day 4: Hofburg, Albertina, Heuriger wine tavern in Grinzing.",
    "Budget: roughly $1,500 excluding flights.",
]

AUSTRIA_FOLDER = "Fun/Travel/Planned/Austria"


def _slug_folder(entry: dict) -> str:
    """Folder slugged per segment, the way KBStore stores it."""
    return "/".join(slugify(s) for s in (entry.get("folder") or "").split("/") if s.strip())


def _kb_entries(result: dict) -> list[dict]:
    return [e for e in result.get("entries", []) if e.get("type") == "kb_entry"]


def _plan_md(lines: list[str]) -> bytes:
    return "\n\n".join(lines).encode()


# ------------------------------------------------------------------ sorting


def check_bucket_list_typed(c, provider):
    """A "someday I want to see X" wish typed into the drop box is a Bucket
    List place (the Travel states: someday -> Bucket List), not a visit."""
    r = drop(c, text=BUCKET_WISH, provider=provider)
    e = first(r, "kb_entry")
    assert _slug_folder(e).startswith("fun/travel/bucket-list"), f"folder={e.get('folder')!r}"
    # Nothing was visited — an experience proposal would invent a trip that never happened.
    assert "experience_entry" not in types(r), types(r)


def check_bucket_list_note(c, provider):
    """Same wish through the folder-aware note: lane — the suggester's own
    travel rule names "Fun/Travel/Bucket List" for places wanted someday."""
    r = drop(c, text=f"note: {BUCKET_WISH}", provider=provider)
    e = first(r, "kb_entry")
    assert _slug_folder(e).startswith("fun/travel/bucket-list"), f"folder={e.get('folder')!r}"
    assert "experience_entry" not in types(r), types(r)


def check_kyoto_experience(c, provider):
    """A trip already taken ("got back from Kyoto") is an Experience: the
    additive check proposes an experience_entry whose city is Kyoto."""
    r = drop(c, text=KYOTO_TRIP, provider=provider)
    exp = first(r, "experience_entry")
    # The city is stated outright; it's what links the experience into the place graph.
    assert "kyoto" in (exp.get("city") or "").lower(), f"city={exp.get('city')!r}"
    assert (exp.get("suggested_name") or "").strip(), exp
    # A past trip must never be filed as a future plan or a someday wish.
    for e in _kb_entries(r):
        f = _slug_folder(e)
        assert not f.startswith("fun/travel/planned"), f"past trip filed as a plan: {e.get('folder')!r}"
        assert not f.startswith("fun/travel/bucket-list"), f"past trip filed as bucket list: {e.get('folder')!r}"


def check_second_plan_reuses_region(c, provider):
    """An Osaka + Nara plan belongs with the already-planned Japan trip:
    the suggester must reuse Fun/Travel/Planned/Japan (or a subfolder),
    not open a parallel Planned/Osaka or a new top-level folder."""
    r = drop(c, data=_plan_md(OSAKA_PLAN), filename="osaka_nara_plan.md", provider=provider)
    assert "document_entry" not in types(r), types(r)  # a trip plan is a note, not a vault document
    f = _slug_folder(first(r, "kb_entry"))
    assert f == "fun/travel/planned/japan" or f.startswith("fun/travel/planned/japan/"), f"folder={f!r}"


# ------------------------------------------------------------------ place graph


def _graph(c) -> dict:
    r = c.get("/graph")
    assert r.status_code == 200, f"/graph {r.status_code}: {r.text[:300]}"
    return r.json()


def _is_vienna(node_id: str) -> bool:
    nid = node_id.lower()
    return nid.startswith("place:europe/austria/vienna") or (nid.startswith("note:places/") and nid.endswith("vienna"))


def _save_vienna_plan(c, provider, *, title: str | None = None, fields: dict | None = None) -> tuple[str, dict]:
    """Drop the Vienna plan (real model writes the note), then Save it into
    Fun/Travel/Planned/Austria exactly as the review card would."""
    proposal = first(drop(c, data=_plan_md(VIENNA_PLAN), filename="vienna_plan.md", provider=provider), "kb_entry")
    body = {"folder": AUSTRIA_FOLDER, "title": title or proposal.get("title") or "Vienna plan",
            "content": proposal.get("content") or "\n\n".join(VIENNA_PLAN), "links": proposal.get("links") or []}
    if fields is not None:
        body["fields"] = fields
    r = c.post("/kb/entries", json=body)
    assert r.status_code == 200, r.text
    saved = r.json()
    return f"note:{saved['folder']}/{saved['slug']}", _graph(c)


def check_vienna_plan_links_place_graph(c, provider):
    """A Planned note whose Destinations say "Vienna, Austria" is located_in
    Vienna, and Vienna chains part_of Austria part_of Europe — so "trips in
    Europe" reaches it by walking the place tree."""
    note_id, g = _save_vienna_plan(c, provider, title="Vienna plan (destinations set)",
                                   fields={"destinations": "Vienna, Austria"})
    edges = g["edges"]
    located = [e["target"] for e in edges if e["source"] == note_id and e["kind"] == "located_in"]
    assert any(_is_vienna(t) for t in located), f"{note_id} located_in {located}"
    city = next(t for t in located if _is_vienna(t))
    parents = {e["source"]: e["target"] for e in edges if e["kind"] == "part_of" and e["source"].startswith(("place:", "note:places/"))}
    assert parents.get(city) == "place:europe/austria", f"{city} part_of {parents.get(city)!r}"
    assert parents.get("place:europe/austria") == "place:europe", parents.get("place:europe/austria")
    # The place nodes are real graph nodes (not dangling ids) with their level.
    levels = {n["id"]: n.get("level") for n in g["nodes"] if n.get("type") == "place"}
    assert levels.get("place:europe/austria") == "country" and levels.get("place:europe") == "continent", levels


def check_vienna_plan_from_drop_links_place_graph(c, provider):
    """The common path: a Vienna plan dropped and saved as proposed (no
    Destinations typed by hand) should still land on Vienna's node — a plan
    that never reaches the place graph is invisible to "trips in Austria".
    The backfill is run too, so any linking path the code has gets its chance."""
    note_id, _ = _save_vienna_plan(c, provider)
    r = c.post("/kb/graph/backfill-places", params={"dry_run": "false"})
    assert r.status_code == 200, r.text
    edges = _graph(c)["edges"]
    linked = [e["target"] for e in edges if e["source"] == note_id and e["kind"] in ("located_in", "at_location")]
    assert any(_is_vienna(t) or t.lower().startswith("place:europe/austria") for t in linked), (
        f"{note_id} is not linked to Vienna/Austria; its place-ish edges: {linked}"
    )


ALL = [
    check_bucket_list_typed,
    check_bucket_list_note,
    check_kyoto_experience,
    check_second_plan_reuses_region,
    check_vienna_plan_links_place_graph,
    check_vienna_plan_from_drop_links_place_graph,
]
