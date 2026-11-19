"""Shared harness for the LIVE suites (tests_local/, tests_owner/).

Unlike tests/ (models faked), these run the app in-process on a sandbox data
dir with the REAL local models via Ollama. Cloud is blocked: a step that can
only work with Claude fails the test with "cloud call blocked". Nothing is
ever written to ~/.quintacle — a seed store is COPIED into a temp dir.
"""
from __future__ import annotations

import json
import mimetypes
import os
import shutil
import sys
import urllib.request
from pathlib import Path

REAL_STORE = Path.home() / ".quintacle"
REAL_USDA = REAL_STORE / "nutrition" / "usda.db"
PERCEPTION_MODELS = Path.home() / ".cache" / "quintacle-golden" / "perception-models"
PARSE_MODEL = "qwen3:8b"
VISION_MODEL = "qwen2.5vl:3b"


class CloudBlocked(RuntimeError):
    pass


def ollama_models() -> set[str] | None:
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2) as r:
            return {m["name"] for m in json.load(r)["models"]}
    except Exception:
        return None


def missing_max() -> str | None:
    if shutil.which(os.environ.get("QUINTACLE_CLAUDE_BIN", "claude")) is None:
        return "the claude CLI isn't on PATH (Max subscription unavailable)"
    return None


def label_png(lines: list[str]) -> bytes:
    """A clean rendered nutrition-label image (real pixels for OCR/vision)."""
    import io

    from PIL import Image, ImageDraw, ImageFont

    font = ImageFont.truetype("/usr/share/fonts/TTF/DejaVuSans.ttf", 30)
    img = Image.new("RGB", (900, 70 + 46 * len(lines)), "white")
    d = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        d.text((40, 35 + 46 * i), line, fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def missing_requirements() -> str | None:
    models = ollama_models()
    if models is None:
        return "Ollama isn't running (start it with `ollama serve`)"
    if PARSE_MODEL not in models:
        return f"Ollama is missing {PARSE_MODEL} (`ollama pull {PARSE_MODEL}`)"
    return None


def _env(data: Path, cloud: bool = False) -> None:
    os.environ["QUINTACLE_DATA_DIR"] = str(data)
    usda = data / "nutrition" / "usda.db"
    if REAL_USDA.exists() and not usda.exists():
        usda.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REAL_USDA, usda)  # copy; the real db is only read
    os.environ["QUINTACLE_USDA_DB"] = str(usda)
    # The installed offline gazetteer is only READ (2026-11-11).
    if (REAL_STORE / "geonames" / "cities.tsv").exists():
        os.environ["QUINTACLE_GEONAMES_DIR"] = str(REAL_STORE / "geonames")
    PERCEPTION_MODELS.mkdir(parents=True, exist_ok=True)
    os.environ["QUINTACLE_PERCEPTION_MODELS_DIR"] = str(PERCEPTION_MODELS)
    # Side effects unrelated to the behaviour under test.
    for k in ("QUINTACLE_SUMMARY_PROVIDER", "QUINTACLE_SOFT_RECORD_PROVIDER", "QUINTACLE_VECTOR_LANE", "QUINTACLE_WEB_SEARCH"):
        os.environ[k] = "off"
    if cloud:
        os.environ.pop("QUINTACLE_DISABLE_MAX", None)
        os.environ["QUINTACLE_CLOUD"] = "max"
    else:
        os.environ["QUINTACLE_DISABLE_MAX"] = "1"  # never shell out to the claude CLI


def _block_cloud() -> None:
    import quintacle_core.llm_dispatch as llm_dispatch
    import quintacle_core.max_backend as max_backend

    real = max_backend.cloud_client

    def blocked(*a, **k):
        raise CloudBlocked("cloud call blocked — this step only worked with Claude")

    for name, mod in list(sys.modules.items()):
        if name.startswith("quintacle_core") and getattr(mod, "cloud_client", None) is real:
            mod.cloud_client = blocked
    llm_dispatch._parse_cloud = blocked


MAX_CALLS: list[str] = []


def _max_only() -> None:
    """Cloud runs go through the Max subscription ONLY: the metered-API
    fallback raises instead of spending money, and every Max call is counted
    so a test can prove Claude actually answered."""
    import quintacle_core.max_backend as max_backend

    real_run = max_backend.run

    def counted(*a, **k):
        out = real_run(*a, **k)
        MAX_CALLS.append(out.get("model") or "max")
        return out

    def no_api(self):
        raise CloudBlocked("Max failed and the metered-API fallback is blocked in tests")

    max_backend.run = counted
    max_backend.CloudClient._api = no_api
    # Chat's Max path falls back through its own direct Anthropic call.
    import quintacle_core.nodes.kb.chat as kb_chat

    def no_chat_api(*a, **k):
        raise CloudBlocked("chat's metered-API fallback is blocked in tests")

    kb_chat._run_anthropic = no_chat_api


def snapshot_real_db(seed: Path) -> None:
    """2026-11-17: the copied store skips *-wal, so writes still in the real database's WAL
    (e.g. today's saved ingredients) were missing from the sandbox. Overwrite the seed's
    quintacle.db with a consistent snapshot read from the real one (read-only open + the
    sqlite backup API; ~/.quintacle is never written)."""
    import sqlite3

    real = REAL_STORE / "quintacle.db"
    if not real.exists():
        return
    src = sqlite3.connect(f"file:{real}?mode=ro", uri=True)
    dst = sqlite3.connect(seed / "quintacle.db")
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


# 2026-11-18: what the owner saved by hand, and when (the ingredients / meals tables carry no
# time). sandbox_before leaves out every one saved at or after `chats_from` on its own, so a
# test written earlier never sees a later save. Add a line whenever he saves one in a test.
OWNER_SAVES: tuple[tuple[str, str, str], ...] = (
    ("2026-11-17-1616", "ingredient", "Costco Lean Lamb"),
    ("2026-11-17-1621", "ingredient", "Kirkland Signature Plain Nonfat Greek Yogurt (2/3 cup)"),
    ("2026-11-18-0820", "ingredient", "Salmon"),  # deleted 2026-11-18, replaced by "Atlantic salmon"
    ("2026-11-18-0845", "ingredient", "Atlantic salmon"),
    ("2026-11-18-0820", "ingredient", "Egg, whole, raw, fresh"),
    ("2026-11-18-0820", "ingredient", "Rice, white, short-grain, raw, unenriched"),
    ("2026-11-18-0820", "meal", "High-Protein Breakfast with Lamb, Salmon, and Eggs(local+local)"),
    ("2026-11-18-0822", "meal", "Lamb, Salmon, and Egg Breakfast with Rice(local+claude)"),
    ("2026-11-18-0823", "meal", "High-Protein Breakfast with Lamb, Salmon, and Eggs(claude +claude) "),
    ("2026-11-18-0825", "meal", "Lamb, Salmon and Egg Breakfast with Rice(claude +claude) "),
    ("2026-11-18-0830", "meal", "High-Protein Breakfast with Lamb, Salmon, and Eggs"),  # the one he kept (others deleted)
)


def sandbox_before(tmp: Path, *, chats_from: str, leave_out: tuple[str, ...] = (),
                   leave_out_ingredients: tuple[str, ...] = (), cloud: bool = False):
    """2026-11-17 (owner: "I thought sandboxing was doing that"): a client over the owner's
    data AS IT WAS just before he did a test by hand. The real store is only read.

    - chats_from "YYYY-MM-DD-HHMM": every saved chat from that minute on is left out: its
      transcript file, its search rows, and the soft facts ("things you told me") it created;
    - leave_out: kb paths (a note without .md, an asset, or a whole folder) saved later;
    - leave_out_ingredients: ingredient names saved later (row, micros, note).
    Their graph edges and search-index entries are removed too."""
    import sqlite3

    seed = tmp / "seed"
    shutil.copytree(REAL_STORE, seed, ignore=shutil.ignore_patterns(
        "models", "*.onnx", "*.zip", "*.lock", "*-shm", "*-wal"))
    snapshot_real_db(seed)
    gone_nodes: list[str] = []
    # -- chats from `chats_from` on
    conv = seed / "conversations"
    late = sorted(str(f.relative_to(conv)) for f in conv.glob("*/*.md") if f.stem >= chats_from)
    for rel in late:
        (conv / rel).unlink()
        if not any((conv / rel).parent.iterdir()):
            (conv / rel).parent.rmdir()
    if late and (conv / "transcripts.db").exists():
        con = sqlite3.connect(conv / "transcripts.db")
        for rel in late:
            con.execute("DELETE FROM transcript_fts WHERE path = ?", (rel,))
            con.execute("DELETE FROM transcript_sessions WHERE path = ?", (rel,))
        con.commit()
        con.close()
    if late and (conv / "soft_record.db").exists():
        con = sqlite3.connect(conv / "soft_record.db")
        con.executemany("DELETE FROM soft_facts WHERE transcript = ?", [(r,) for r in late])
        con.commit()
        con.close()
    gone_nodes += [f"transcript:{r[:-3]}" for r in late]
    # -- kb notes / folders saved later
    kb = seed / "kb"
    for rel in leave_out:
        target = kb / rel
        files = [target.with_suffix(".md")] if not target.exists() and target.with_suffix(".md").exists() else (
            [f for f in target.rglob("*") if f.is_file()] if target.is_dir() else [target])
        for f in files:
            if f.exists():
                gone_nodes.append(f"note:{f.relative_to(kb).with_suffix('').as_posix()}")
                f.unlink()
        if target.is_dir():
            for d in sorted((x for x in target.rglob("*") if x.is_dir()), reverse=True):
                gone_nodes.append(f"folder:{d.relative_to(kb).as_posix()}")
                d.rmdir()
            gone_nodes.append(f"folder:{target.relative_to(kb).as_posix()}")
            target.rmdir()
    # -- ingredients / meals saved later (explicit, plus OWNER_SAVES from chats_from on)
    leave_out_ingredients = tuple(dict.fromkeys(
        (*leave_out_ingredients, *(n for t, k, n in OWNER_SAVES if k == "ingredient" and t >= chats_from))))
    late_meals = [n for t, k, n in OWNER_SAVES if k == "meal" and t >= chats_from]
    if late_meals:
        from quintacle_core.markdown_paths import slugify

        con = sqlite3.connect(seed / "quintacle.db")
        for name in late_meals:
            for (i,) in con.execute("SELECT id FROM meals WHERE name = ?", (name,)).fetchall():
                con.execute("DELETE FROM meal_ingredients WHERE meal_id = ?", (i,))
                con.execute("DELETE FROM meals WHERE id = ?", (i,))
                gone_nodes.append(f"meal:{i}")
            note = kb / "personal-development/physical/nutrition/presets" / f"{slugify(name)}.md"
            if note.exists():
                gone_nodes.append(f"note:{note.relative_to(kb).with_suffix('').as_posix()}")
                note.unlink()
        con.commit()
        con.close()
    if leave_out_ingredients:
        from quintacle_core.markdown_paths import slugify

        con = sqlite3.connect(seed / "quintacle.db")
        for name in leave_out_ingredients:
            for (i,) in con.execute("SELECT id FROM ingredients WHERE name = ?", (name,)).fetchall():
                con.execute("DELETE FROM ingredient_micros WHERE ingredient_id = ?", (i,))
                con.execute("DELETE FROM ingredients WHERE id = ?", (i,))
                gone_nodes.append(f"ingredient:{i}")
            note = kb / "personal-development/physical/nutrition/ingredients" / f"{slugify(name)}.md"
            if note.exists():
                gone_nodes.append(f"note:{note.relative_to(kb).with_suffix('').as_posix()}")
                note.unlink()
        con.commit()
        con.close()
    client = make_client(tmp, seed_store=seed, cloud=cloud)
    from quintacle_core.graph import get_graph_store
    from quintacle_core.retrieval import get_retrieval_index

    for node in gone_nodes:
        get_graph_store().remove_edges_for(node)
        get_retrieval_index().remove_node(node)
    return client


def make_client(tmp: Path, seed_store: Path | None = None, cloud: bool = False):
    """A TestClient over a fresh app on tmp/data. seed_store (e.g. the real
    ~/.quintacle) is copied in first, minus model weights."""
    data = tmp / "data"
    if seed_store is not None and seed_store.exists():
        shutil.copytree(
            seed_store, data,
            ignore=shutil.ignore_patterns("models", "*.onnx", "*.zip", "*.lock", "*-shm", "*-wal"),
        )
    data.mkdir(parents=True, exist_ok=True)
    _env(data, cloud=cloud)
    from fastapi.testclient import TestClient

    import quintacle_core.api as api_module

    api_module.DATA_DIR = data
    client = TestClient(api_module.create_app())
    if cloud:
        _max_only()
    else:
        _block_cloud()
    return client


def drop(client, *, text: str = "", path: Path | None = None, data: bytes | None = None,
         filename: str | None = None, provider: str | None = None) -> dict:
    form = {"text": text}
    if provider:
        form["provider"] = provider
    files = None
    if path is not None or data is not None:
        name = filename or path.name
        body = data if data is not None else path.read_bytes()
        mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
        files = {"file": (name, body, mime)}
    r = client.post("/drop", data=form, files=files)
    assert r.status_code == 200, f"/drop {r.status_code}: {r.text[:400]}"
    return r.json()


def types(result: dict) -> list[str]:
    return [e.get("type") for e in result.get("entries", [])]


def first(result: dict, entry_type: str) -> dict:
    for e in result.get("entries", []):
        if e.get("type") == entry_type:
            return e
    raise AssertionError(f"no {entry_type} proposed; got {types(result)}: {json.dumps(result.get('entries'))[:600]}")


def folder_of(entry: dict) -> str:
    return (entry.get("folder") or "").strip("/").lower()


def make_pdf(lines: list[str]) -> bytes:
    """A minimal one-page text PDF (real text layer, read by pypdf)."""
    def esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    body = "BT /F1 10 Tf 40 800 Td 13 TL " + " ".join(f"({esc(l)}) '" for l in lines) + " ET"
    objs = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(body)} >>\nstream\n{body}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out
