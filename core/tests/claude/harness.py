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
