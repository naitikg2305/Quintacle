"""The two on-demand updaters (docs/reference/career-updates.md):
Build A (work logs -> master career record, append-only, watermarked) and
Build B (knowledge notes / record entries -> PersonalWebsite markdown on a
new local git branch).

Everything is sandboxed: a tmp DATA_DIR per test, models stubbed at the
parse_structured seam, and a throwaway git repo standing in for the website
— ~/.quintacle, ~/Career and Resume and ~/code/PersonalWebsite are never
read or written here.
"""
from __future__ import annotations

import subprocess
from datetime import date

import frontmatter
import pytest
from fastapi.testclient import TestClient

from quintacle_core.llm_dispatch import ParseResult
from quintacle_core.nodes.career import draft as draft_mod
from quintacle_core.nodes.career import record as rec_mod
from quintacle_core.nodes.career import website as web_mod
from quintacle_core.nodes.career.draft import DraftBullet, EntryDraft
from quintacle_core.nodes.career.validate import check_bullet
from quintacle_core.nodes.career.website import Ranking, RankItem

TODAY = date(2026, 11, 5)

# Shaped like the real record: numbered periods, `### N.M` entries, labelled
# blocks, backticked provenance tags, a non-entry tail section.
RECORD = """**Compiled:** 2026-09-30

---

## 1. Identity and positioning

| Field | Current |
|---|---|
| Name | Test Person |

---

## 5. 2024 – May 2025 · University of Maryland, years 3–4

### 5.1 Project — Quintacle v1, "AI personal assistant" (Jan 2024 – 2025) `[R]`
- Early voice assistant prototype. `[R]`

---

## 7. Jan 2026 – present · Minfy Technologies, AI Engineer, Tysons VA

### 7.1 Generalized AI evaluation test bench (Feb – Aug 2026) `[R][C]`
**What it is.** A black-box evaluation harness.

**What I did**
- FastAPI service + CLI sharing Pydantic models.
- Sliding-window chunking 512 chars / 64 overlap.

**Tech.** Python 3.11, FastAPI, ChromaDB.

**Resume phrasing bank**
- Developed a generalized AI evaluation test bench scoring endpoints via cosine similarity. `[R 2026]`
- Built a dual SQL oracle for Chat-BI endpoints. `[?]`

### 7.7 Personal project — The Quintacle rebuild (Sep 2026) `[C]`
**What I did**
- Rebuilt the deterministic core over markdown files. `[C]`

**Tech.** Python, FastAPI, Next.js.

---

## 12. Source index

- Repos: ~/code/quintacle
"""


def log_text(day: str, *sessions: tuple[str, str]) -> str:
    out = [f"# {day}", ""]
    for i, (where, summary) in enumerate(sessions, start=1):
        out += [
            f"## Session {i}",
            "",
            f"**Session:** ~10:00–12:00 (local) · **Where:** {where} · **Who:** Owner + Claude",
            "",
            "**Summary**",
            summary,
            "",
        ]
    return "\n".join(out)


@pytest.fixture
def app(tmp_path, monkeypatch):
    import quintacle_core.api as api_module
    from quintacle_core import clock

    monkeypatch.setattr(api_module, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(clock, "today", lambda: TODAY)
    monkeypatch.setenv("QUINTACLE_WEBSITE_REPO", str(tmp_path / "site"))
    monkeypatch.delenv("QUINTACLE_CAREER_RECORD_FOLDER", raising=False)
    monkeypatch.delenv("QUINTACLE_CAREER_RECORD_TITLE", raising=False)
    client = TestClient(api_module.create_app())
    client.data_dir = tmp_path / "data"
    return client


def kb():
    from quintacle_core.nodes.kb.api import get_store

    return get_store()


def seed_hubs(c):
    assert c.post("/kb/entries", json={"folder": "Career", "title": "Minfy", "content": "Employer hub."}).status_code == 200
    assert c.post("/kb/entries", json={"folder": "Projects", "title": "Quintacle", "content": "Project hub."}).status_code == 200


def import_record(c, text=RECORD):
    r = c.post("/career/record/import", json={"content": text})
    assert r.status_code == 200, r.text
    return r.json()


def import_log(c, day: str, text: str):
    r = c.post("/logs/worklog/import", json={"date": day, "content": text})
    assert r.status_code == 200, r.text
    return r.json()


def stub_drafter(monkeypatch, make_bullets):
    """make_bullets(user_prompt) -> list[DraftBullet]; records every prompt."""
    prompts = []

    def fake(system, user, output_format, *, provider=None, max_tokens=4096):
        prompts.append(user)
        return ParseResult(EntryDraft(bullets=make_bullets(user)), "local")

    monkeypatch.setattr(draft_mod, "parse_structured", fake)
    return prompts


def record_text(c) -> str:
    st = c.get("/career/record").json()
    return kb().read(st["folder"], st["slug"])


# --- record parsing + validation (pure) ---------------------------------------


def test_parse_finds_entries_sections_and_no_watermark():
    rec = rec_mod.parse(RECORD)
    assert [e.id for e in rec.entries] == ["5.1", "7.1", "7.7"]
    assert rec.covered_through is None
    assert rec.entry("7.1").tech == ["Python 3.11", "FastAPI", "ChromaDB"]
    kinds = [b["kind"] for b in rec_mod.entry_bullets(rec, "7.1")]
    assert kinds == ["detail", "detail", "phrasing", "phrasing"]
    assert "Minfy Technologies" in rec_mod.org_names(rec)


def test_watermark_marker_round_trips():
    text, _ = rec_mod.apply_additions(RECORD, [], [], date(2026, 11, 2))
    assert text.rstrip().endswith("_Covered through: 2026-11-02_")
    assert rec_mod.parse(text).covered_through == date(2026, 11, 2)
    again, _ = rec_mod.apply_additions(text, [], [], "2026-11-04")
    assert again.count("_Covered through:") == 1
    assert rec_mod.parse(again).covered_through == date(2026, 11, 4)


def test_fact_validation_rejects_invented_numbers_dates_employers_titles():
    corpus = "Cut p95 latency from 900 ms to 310 ms on the bench (Minfy). Wrote the README."
    employers = {"Minfy", "Zillion Technologies"}
    assert check_bullet("Cut p95 latency from 900 ms to 310 ms.", corpus, employers) == []
    assert any("40" in r for r in check_bullet("Cut latency by 40%.", corpus, employers))
    assert any("2025" in r for r in check_bullet("Shipped the bench in 2025.", corpus, employers))
    assert any("March" in r for r in check_bullet("Shipped the bench in March.", corpus, employers))
    assert any("Zillion" in r for r in check_bullet("Built it for Zillion Technologies.", corpus, employers))
    assert any("senior" in r for r in check_bullet("Promoted to Senior Engineer.", corpus, employers))
    assert any("PhD" in r for r in check_bullet("Used PhD-level methods.", corpus, employers))
    assert any("three" in r for r in check_bullet("Led three engineers.", corpus, employers))
    # "may" as a verb is not a month
    assert check_bullet("Wrote a README that may help onboarding.", corpus, employers) == []
    # thousands separators + p95 survive normalization
    assert check_bullet("Cut p95 latency to 310 ms.", corpus + " 1,200 rows", employers) == []


# --- Build A: run -------------------------------------------------------------


def test_run_without_watermark_requires_start_date(app, monkeypatch):
    seed_hubs(app)
    import_record(app)
    stub_drafter(monkeypatch, lambda u: [])
    r = app.post("/career/record/run", json={})
    assert r.status_code == 400
    assert "start date" in r.text


def test_watermark_selection_is_after_exclusive_and_until_yesterday(app, monkeypatch):
    seed_hubs(app)
    import_record(app, RECORD + "\n_Covered through: 2026-11-01_\n")
    for day in ("2026-11-01", "2026-11-02", "2026-11-04", "2026-11-05"):
        import_log(app, day, log_text(day, ("~/code/quintacle", f"Worked on Quintacle on {day}.")))
    stub_drafter(monkeypatch, lambda u: [])
    body = app.post("/career/record/run", json={}).json()
    # the watermark day itself is already covered; today waits by default
    assert body["dates"] == ["2026-11-02", "2026-11-04"]
    assert body["through"] == "2026-11-04"
    dates = [s["date"] for g in body["groups"] for s in g["sessions"]]
    assert dates == ["2026-11-02", "2026-11-04"]

    with_today = app.post("/career/record/run", json={"include_today": True}).json()
    assert with_today["through"] == "2026-11-05"


def test_start_date_is_inclusive_when_no_watermark(app, monkeypatch):
    seed_hubs(app)
    import_record(app)
    for day in ("2026-11-01", "2026-11-02"):
        import_log(app, day, log_text(day, ("~/code/quintacle", "Worked on Quintacle.")))
    stub_drafter(monkeypatch, lambda u: [])
    body = app.post("/career/record/run", json={"start": "2026-11-02"}).json()
    assert body["dates"] == ["2026-11-02"]


def test_private_and_placeholder_logs_are_skipped_and_never_prompted(app, monkeypatch):
    seed_hubs(app)
    import_record(app, RECORD + "\n_Covered through: 2026-10-31_\n")
    import_log(app, "2026-11-01", log_text("2026-11-01", ("~/code/quintacle", "SECRETPRIVATE Quintacle work.")))
    kb().set_private("daily-log/work-logs", "work-log-2026-11-01", True)
    import_log(
        app,
        "2026-11-02",
        "# 2026-11-02\n\n- ⚠️ 14:28 session ended without a log entry · cwd `/home/x/code/quintacle` · reason `other`\n",
    )
    mixed = "# 2026-11-03\n\n- ⚠️ 09:00 session ended without a log entry · cwd `/x/quintacle`\n\n" + log_text(
        "2026-11-03", ("~/code/quintacle", "Built the Quintacle career page.")
    ).split("\n", 1)[1]
    import_log(app, "2026-11-03", mixed)
    prompts = stub_drafter(monkeypatch, lambda u: [])
    body = app.post("/career/record/run", json={}).json()
    assert body["skipped"]["private"] == ["2026-11-01"]
    assert body["skipped"]["placeholder"] == ["2026-11-02"]
    assert body["through"] == "2026-11-03"
    joined = "\n".join(prompts)
    assert "SECRETPRIVATE" not in joined
    assert "session ended without a log entry" not in joined
    assert "Built the Quintacle career page." in joined


def test_sessions_group_by_the_hub_they_mention(app, monkeypatch):
    seed_hubs(app)
    import_record(app, RECORD + "\n_Covered through: 2026-11-01_\n")
    import_log(
        app,
        "2026-11-02",
        log_text(
            "2026-11-02",
            ("~/code/minfy/bench", "Minfy bench: added a latency report."),
            ("~/code/quintacle", "Quintacle: built the career page."),
            ("~/code/dotfiles", "Tidied dotfiles."),
        ),
    )
    stub_drafter(monkeypatch, lambda u: [])
    body = app.post("/career/record/run", json={}).json()
    by_hub = {g["hub"]["title"]: g for g in body["groups"]}
    assert set(by_hub) == {"Minfy", "Quintacle"}
    assert any("latency report" in line for s in by_hub["Minfy"]["sessions"] for line in s["lines"])
    assert not any("career page" in line for s in by_hub["Minfy"]["sessions"] for line in s["lines"])
    assert body["skipped"]["unlinked_sessions"] == 1


def test_hub_to_entry_mapping_field_title_ambiguous(app):
    seed_hubs(app)
    import_record(app)
    app.post("/kb/entries", json={"folder": "Projects", "title": "NaviGatr", "content": "hub"})
    hubs = {h["title"]: h for h in app.get("/career/hubs").json()}
    # "Quintacle" is in both 5.1 and 7.7 titles -> owner picks
    assert hubs["Quintacle"]["mapping"]["entry_id"] is None
    assert hubs["Quintacle"]["mapping"]["candidates"] == ["5.1", "7.7"]
    # "Minfy" only in the period heading -> that period's entries
    assert hubs["Minfy"]["mapping"]["candidates"] == ["7.1", "7.7"]
    assert hubs["NaviGatr"]["mapping"]["note"] == "no match"
    # explicit field wins
    r = app.put("/career/hubs", json={"folder": "projects", "slug": "quintacle", "record_entry": "7.7"})
    assert r.status_code == 200
    hubs = {h["title"]: h for h in app.get("/career/hubs").json()}
    assert hubs["Quintacle"]["mapping"] == {"entry_id": "7.7", "how": "field", "candidates": []}
    # the record note itself is never a hub
    assert "Master Career Record" not in hubs


def test_title_match_maps_a_unique_entry():
    from quintacle_core.nodes.career.hubs import Hub, map_hub

    hub = Hub("projects", "test-bench", "test bench", "projects", False, None, False, "test bench", "", "test-bench")
    assert map_hub(hub, rec_mod.parse(RECORD))["entry_id"] == "7.1"


def test_drafts_are_validated_tagged_and_carry_sources(app, monkeypatch):
    seed_hubs(app)
    import_record(app, RECORD + "\n_Covered through: 2026-11-01_\n")
    app.put("/career/hubs", json={"folder": "career", "slug": "minfy", "record_entry": "7.1"})
    import_log(app, "2026-11-02", log_text("2026-11-02", ("~/code/minfy", "Minfy bench: cut judge latency from 900 ms to 310 ms.")))
    import_log(app, "2026-11-04", log_text("2026-11-04", ("~/code/minfy", "Minfy bench: added an S3 ingest smoke test.")))

    def bullets(user):
        lines = {int(l.split("]", 1)[0][1:]): l for l in user.splitlines() if l.startswith("[")}
        n_latency = next(n for n, l in lines.items() if "900 ms" in l)
        n_s3 = next(n for n, l in lines.items() if "S3 ingest" in l)
        return [
            DraftBullet(text="Cut LLM-judge latency from 900 ms to 310 ms. [R 2026]", section="phrasing", sources=[n_latency]),
            DraftBullet(text="Cut judge latency by 65%, saving $4,000 a month.", section="phrasing", sources=[n_latency]),
            DraftBullet(text="Added an S3 ingest smoke test.", section="detail", sources=[n_s3]),
            DraftBullet(text="Did something with no sources.", section="detail", sources=[]),
            DraftBullet(text="Developed a generalized AI evaluation test bench scoring endpoints via cosine similarity.", section="phrasing", sources=[n_s3]),
        ]

    stub_drafter(monkeypatch, bullets)
    body = app.post("/career/record/run", json={}).json()
    (g,) = body["groups"]
    assert g["entry"]["id"] == "7.1"
    accepted = {b["text"]: b for b in g["bullets"]}
    assert set(accepted) == {"Cut LLM-judge latency from 900 ms to 310 ms.", "Added an S3 ingest smoke test."}
    assert accepted["Cut LLM-judge latency from 900 ms to 310 ms."]["date"] == "2026-11-02"
    assert accepted["Added an S3 ingest smoke test."]["date"] == "2026-11-04"
    assert "900 ms" in accepted["Cut LLM-judge latency from 900 ms to 310 ms."]["sources"][0]["text"]
    reasons = {b["text"]: " ".join(b["reasons"]) for b in g["rejected"]}
    assert "65" in reasons["Cut judge latency by 65%, saving $4,000 a month."]
    assert "4000" in reasons["Cut judge latency by 65%, saving $4,000 a month."]
    assert "no source" in reasons["Did something with no sources."]
    assert "already in the record" in reasons[
        "Developed a generalized AI evaluation test bench scoring endpoints via cosine similarity."
    ]
    assert body["provider_used"] == "local"


def test_model_failure_is_isolated_per_hub(app, monkeypatch):
    seed_hubs(app)
    import_record(app, RECORD + "\n_Covered through: 2026-11-01_\n")
    import_log(app, "2026-11-02", log_text("2026-11-02", ("~/code/quintacle", "Quintacle work.")))

    def boom(*a, **k):
        raise RuntimeError("ollama down")

    monkeypatch.setattr(draft_mod, "parse_structured", boom)
    body = app.post("/career/record/run", json={}).json()
    assert body["groups"][0]["error"].startswith("ollama down")


# --- Build A: save --------------------------------------------------------------


def test_save_is_append_only_moves_watermark_and_writes_nothing_before(app, monkeypatch):
    seed_hubs(app)
    import_record(app, RECORD + "\n_Covered through: 2026-11-01_\n")
    import_log(app, "2026-11-02", log_text("2026-11-02", ("~/code/minfy", "Minfy bench: added a latency report.")))
    before = record_text(app)
    stub_drafter(monkeypatch, lambda u: [DraftBullet(text="Added a latency report.", section="phrasing", sources=[1])])
    run = app.post("/career/record/run", json={}).json()
    assert record_text(app) == before  # Run never writes

    r = app.post(
        "/career/record/save",
        json={
            "through": run["through"],
            "base_hash": run["base_hash"],
            "bullets": [
                {"entry_id": "7.1", "section": "phrasing", "text": "Added a latency report.", "date": "2026-11-02"},
                {"entry_id": "7.1", "section": "detail", "text": "Owner-edited detail line.", "date": "2026-11-02"},
                {"entry_id": "7.7", "section": "phrasing", "text": "Wrote the career updater.", "date": "2026-11-02"},
            ],
            "new_entries": [
                {
                    "section": 7,
                    "title": "Personal project — Career updater (Nov 2026)",
                    "hub_folder": "projects",
                    "hub_slug": "quintacle",
                    "bullets": [{"section": "phrasing", "text": "Built it.", "date": "2026-11-02"}],
                }
            ],
            "mappings": [{"hub_folder": "career", "hub_slug": "minfy", "entry_id": "7.1"}],
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["new_entries"] == ["7.8"]
    after = record_text(app)

    # every original line survives, in order (watermark line aside)
    old = [l for l in before.split("\n") if not l.startswith("_Covered through")]
    new = after.split("\n")
    it = iter(new)
    assert all(any(l == n for n in it) for l in old)
    assert "_Covered through: 2026-11-02_" in after and "2026-11-01_" not in after

    rec = rec_mod.parse(after.split("\n", 2)[2])
    b71 = rec_mod.entry_bullets(rec, "7.1")
    assert b71[2] == {"text": "Owner-edited detail line.", "raw": "Owner-edited detail line. `[WL 2026-11-02]`", "tags": ["[WL 2026-11-02]"], "kind": "detail"}
    assert b71[-1]["text"] == "Added a latency report." and b71[-1]["kind"] == "phrasing"
    # 7.7 had no phrasing bank -> a labelled block was added inside 7.7
    assert [b["kind"] for b in rec_mod.entry_bullets(rec, "7.7")] == ["detail", "phrasing"]
    assert rec.entry("7.8").title.startswith("Personal project — Career updater")
    assert rec.entry("7.8").section == 7
    # remembered mappings
    hubs = {h["title"]: h for h in app.get("/career/hubs").json()}
    assert hubs["Minfy"]["record_entry"] == "7.1"
    assert hubs["Quintacle"]["record_entry"] == "7.8"

    # stale base -> 409, nothing written
    r2 = app.post("/career/record/save", json={"through": "2026-11-03", "base_hash": run["base_hash"], "bullets": []})
    assert r2.status_code == 409
    assert record_text(app) == after

    # the next run starts after the new watermark
    nxt = app.post("/career/record/run", json={}).json()
    assert nxt["dates"] == []


def test_private_record_note_is_refused(app):
    import_record(app)
    st = app.get("/career/record").json()
    kb().set_private(st["folder"], st["slug"], True)
    r = app.post("/career/record/run", json={"start": "2026-11-01"})
    assert r.status_code == 409


# --- Build B: website -----------------------------------------------------------------


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout


@pytest.fixture
def site(tmp_path):
    repo = tmp_path / "site"
    content = repo / "frontend/public/content"
    (content / "employment").mkdir(parents=True)
    (content / "projects/Software/quintacle").mkdir(parents=True)
    (content / "knowledge").mkdir(parents=True)
    (content / "employment/minfy-technologies.md").write_text(
        '---\ntitle: "AI Engineer"\norder: 1\ncompany: "Minfy Technologies"\ndates: "Jan 2026 – Present"\n'
        'location: "Tysons, VA"\nslug: "minfy-technologies"\nsummaryPoints:\n  - AI engineering.\n'
        'positions:\n  - role: "AI Engineer"\n    dates: "Jan 2026 – Present"\n    bullets:\n      - main: "Existing bullet."\n---\n',
        encoding="utf-8",
    )
    (content / "projects/Software/quintacle/index.md").write_text(
        '---\ntitle: "The Quintacle"\ncategory: "software"\norder: 1\n---\n\n# The Quintacle\n\nHand-written page.\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "Test")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "init")
    return repo


def stub_ranker(monkeypatch, verdict=lambda c: True):
    prompts = []

    def fake(system, user, output_format, *, provider=None, max_tokens=4096):
        prompts.append(user)
        ids = [l.removeprefix("id: ") for l in user.splitlines() if l.startswith("id: ")]
        return ParseResult(Ranking(items=[RankItem(id=i, website=verdict(i), reason="looks technical") for i in ids]), "local")

    monkeypatch.setattr(web_mod, "parse_structured", fake)
    return prompts


def note(c, folder, title, content):
    r = c.post("/kb/entries", json={"folder": folder, "title": title, "content": content})
    assert r.status_code == 200
    return f"note:{r.json()['folder']}/{r.json()['slug']}"


def test_website_candidates_filter_private_excluded_and_hubs(app, monkeypatch, site):
    seed_hubs(app)
    good = note(app, "Knowledge/Tech Notes", "Docker mental model", "Containers are processes. Images are layers.")
    note(app, "Daily Log", "Monday", "Went for a run.")
    note(app, "Me", "Allergies", "Peanuts.")
    note(app, "Organisation/Finance", "Budget", "Rent.")
    secret = note(app, "Knowledge/Tech Notes", "Secret", "SECRETNOTE content.")
    kb().set_private("knowledge/tech-notes", "secret", True)
    prompts = stub_ranker(monkeypatch)
    body = app.post("/career/website/run", json={}).json()
    ids = [c["id"] for c in body["candidates"]]
    assert ids == [good]
    assert secret not in ids
    assert "SECRETNOTE" not in "\n".join(prompts)
    (c,) = body["candidates"]
    assert c["suggest"] is True and c["reason"] == "looks technical"
    assert c["target_path"] == "knowledge/docker-mental-model.md"


def test_reject_is_remembered_until_the_note_is_edited(app, monkeypatch, site):
    nid = note(app, "Knowledge/Tech Notes", "Git tricks", "Use reflog.")
    stub_ranker(monkeypatch)
    (c,) = app.post("/career/website/run", json={}).json()["candidates"]
    assert app.post("/career/website/reject", json={"id": c["id"], "stamp": c["stamp"]}).status_code == 200
    assert app.post("/career/website/run", json={}).json()["candidates"] == []
    # an edit restamps `edited` -> suggested again
    import time

    time.sleep(1.1)
    note(app, "Knowledge/Tech Notes", "Git tricks", "Use reflog. And bisect.")
    again = app.post("/career/website/run", json={}).json()["candidates"]
    assert [x["id"] for x in again] == [nid]


def test_alias_gating_blocks_non_public_hubs_and_renames_public_ones(app, monkeypatch, site):
    seed_hubs(app)
    blocked = note(app, "Knowledge/Tech Notes", "Bench notes", "What I learned building the bench at Minfy.")
    renamed = note(app, "Knowledge/Tech Notes", "Graph notes", "How Quintacle stores edges.")
    app.put("/career/hubs", json={"folder": "projects", "slug": "quintacle", "public": True, "public_name": "The Quintacle"})
    prompts = stub_ranker(monkeypatch)
    body = app.post("/career/website/run", json={}).json()
    by_id = {c["id"]: c for c in body["candidates"] if c["kind"] == "knowledge"}
    assert by_id[blocked]["blocked"] == ["Minfy"] and by_id[blocked]["suggest"] is False
    assert "Bench notes" not in "\n".join(prompts)  # blocked notes aren't even ranked
    assert by_id[renamed]["blocked"] == []

    out = app.post(
        "/career/website/generate", json={"through": body["through"], "items": [{"id": blocked}, {"id": renamed, "category": "Systems"}]}
    ).json()
    assert [s["id"] for s in out["skipped"]] == [blocked]
    assert [f["path"] for f in out["files"]] == ["frontend/public/content/knowledge/graph-notes.md"]
    text = git(site, "show", f"{out['branch']}:frontend/public/content/knowledge/graph-notes.md")
    post = frontmatter.loads(text)
    assert post["title"] == "Graph notes" and post["category"] == "Systems" and post["slug"] == "graph-notes"
    assert "How The Quintacle stores edges." in post.content
    assert "Minfy" not in text


def test_non_public_hub_entries_never_reach_the_site(app, monkeypatch, site):
    seed_hubs(app)
    import_record(app)
    app.put("/career/hubs", json={"folder": "career", "slug": "minfy", "record_entry": "7.1"})  # public NOT set
    app.put("/career/hubs", json={"folder": "projects", "slug": "quintacle", "record_entry": "7.7"})
    stub_ranker(monkeypatch)
    body = app.post("/career/website/run", json={}).json()
    assert [c for c in body["candidates"] if c["kind"] != "knowledge"] == []
    out = app.post("/career/website/generate", json={"items": [{"id": "entry:7.1"}]}).json()
    assert out["branch"] is None and out["skipped"][0]["reason"] == "no PUBLIC hub maps to this entry"
    assert git(site, "branch", "--list", "quintacle/*").strip() == ""


def test_generate_writes_a_new_branch_without_touching_the_checkout(app, monkeypatch, site):
    seed_hubs(app)
    record = RECORD.replace(
        "- Built a dual SQL oracle for Chat-BI endpoints. `[?]`",
        "- Built a dual SQL oracle for Chat-BI endpoints. `[?]`\n- Added a latency report for Minfy clients. `[WL 2026-11-02]`",
    )
    import_record(app, record)
    app.put("/career/hubs", json={"folder": "career", "slug": "minfy", "record_entry": "7.1", "public": True, "public_name": "Minfy Technologies"})
    app.put("/career/hubs", json={"folder": "projects", "slug": "quintacle", "record_entry": "7.7", "public": True, "public_name": "The Quintacle", "public_repo": "https://github.com/x/quintacle"})
    stub_ranker(monkeypatch)
    body = app.post("/career/website/run", json={}).json()
    entry_ids = sorted(c["id"] for c in body["candidates"] if c["kind"] != "knowledge")
    assert entry_ids == ["entry:7.1", "entry:7.7"]
    head_before = git(site, "rev-parse", "HEAD").strip()

    out = app.post("/career/website/generate", json={"items": [{"id": "entry:7.1"}, {"id": "entry:7.7"}]}).json()
    assert out["branch"] == "quintacle/content-2026-11-05"
    # owner's checkout untouched: same branch, same HEAD, clean tree
    assert git(site, "rev-parse", "--abbrev-ref", "HEAD").strip() == "main"
    assert git(site, "rev-parse", "HEAD").strip() == head_before
    assert git(site, "status", "--porcelain").strip() == ""
    paths = {f["path"]: f["status"] for f in out["files"]}
    assert paths == {
        "frontend/public/content/employment/minfy-technologies.md": "M",
        "frontend/public/content/projects/Software/quintacle/index.md": "M",
    }
    emp = frontmatter.loads(git(site, "show", f"{out['branch']}:frontend/public/content/employment/minfy-technologies.md"))
    mains = [b["main"] for b in emp["positions"][0]["bullets"]]
    assert mains == ["Existing bullet.", "Added a latency report for Minfy Technologies clients."]
    proj = git(site, "show", f"{out['branch']}:frontend/public/content/projects/Software/quintacle/index.md")
    assert "Hand-written page." in proj and "quintacle:highlights:start" in proj
    assert "Rebuilt the deterministic core over markdown files." in proj
    assert "[?]" not in proj and "dual SQL oracle" not in emp.content

    # published entries are remembered -> not candidates again until they change
    again = app.post("/career/website/run", json={}).json()
    assert [c for c in again["candidates"] if c["kind"] != "knowledge"] == []
    st = app.get("/career/website").json()
    assert st["last_result"]["branch"] == "quintacle/content-2026-11-05"

    # same-day second branch gets a suffix
    note(app, "Knowledge/Tech Notes", "Venv", "Python virtual environments isolate packages.")
    nid = [c for c in app.post("/career/website/run", json={}).json()["candidates"]][0]["id"]
    out2 = app.post("/career/website/generate", json={"items": [{"id": nid}]}).json()
    assert out2["branch"] == "quintacle/content-2026-11-05-2"


def test_dirty_tree_aborts_without_writing(app, monkeypatch, site):
    nid = note(app, "Knowledge/Tech Notes", "Venv", "Python virtual environments isolate packages.")
    stub_ranker(monkeypatch)
    run = app.post("/career/website/run", json={}).json()
    (site / "frontend/public/content/knowledge/wip.md").write_text("owner's draft", encoding="utf-8")
    r = app.post("/career/website/generate", json={"through": run["through"], "items": [{"id": nid}]})
    assert r.status_code == 409
    assert "uncommitted" in r.json()["detail"]
    assert git(site, "branch", "--list", "quintacle/*").strip() == ""
    assert (site / "frontend/public/content/knowledge/wip.md").read_text() == "owner's draft"
    # watermark did not move: the candidate is still there
    assert app.get("/career/website").json()["watermark"] is None


def test_generate_rechecks_privacy(app, monkeypatch, site):
    nid = note(app, "Knowledge/Tech Notes", "Venv", "Python virtual environments isolate packages.")
    stub_ranker(monkeypatch)
    run = app.post("/career/website/run", json={}).json()
    kb().set_private("knowledge/tech-notes", "venv", True)
    out = app.post("/career/website/generate", json={"through": run["through"], "items": [{"id": nid}]}).json()
    assert out["branch"] is None and out["skipped"] == [{"id": nid, "reason": "note is private"}]
    # empty generate still moves the watermark (owner reviewed this run)
    assert out["watermark"] == run["through"]


def test_settings_record_location_is_configurable(app):
    r = app.put("/career/settings", json={"record_folder": "Career/Records", "record_title": "Career Record"}).json()
    assert r["record_folder"] == "Career/Records" and r["record_title"] == "Career Record"
    import_record(app)
    st = app.get("/career/record").json()
    assert (st["folder"], st["slug"]) == ("career/records", "career-record")
    assert st["exists"] is True
    assert app.post("/career/record/import", json={"content": RECORD}).status_code == 409


# --- phone / Termux: no PersonalWebsite checkout, maybe no git (2026-11-05) ---


def test_website_repo_missing_is_a_clear_error(tmp_path):
    with pytest.raises(web_mod.WebsiteRepoError, match="website repo not found"):
        web_mod.write_branch(tmp_path / "no-such-site", "frontend/public/content", {"knowledge/x.md": "x"}, "msg")


def test_git_missing_is_a_clear_error_not_a_crash(tmp_path, monkeypatch):
    (tmp_path / "site").mkdir()

    def no_git(*a, **kw):
        raise FileNotFoundError("git")

    monkeypatch.setattr(web_mod.subprocess, "run", no_git)
    with pytest.raises(web_mod.WebsiteRepoError, match="git is not installed"):
        web_mod.check_repo(tmp_path / "site")


def test_website_status_works_without_repo(app):
    r = app.get("/career/website")
    assert r.status_code == 200
    assert r.json()["repo"].endswith("site")
