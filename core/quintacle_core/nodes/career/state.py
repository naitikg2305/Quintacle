"""Small JSON state for the career updaters, kept in the data dir (NOT in
kb/, so no model-facing surface ever walks it):

  <data_dir>/career/settings.json   record note location overrides
  <data_dir>/career/website.json    website watermark, last run, rejects,
                                    published-entry hashes, last result

Config precedence for the record note: settings.json > env
(QUINTACLE_CAREER_RECORD_FOLDER / _TITLE) > defaults (Career / Master Career
Record). The website repo is env-only (QUINTACLE_WEBSITE_REPO, default
~/code/PersonalWebsite) — a path that git runs in shouldn't be settable from
a web form.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT_RECORD_FOLDER = "Career"
DEFAULT_RECORD_TITLE = "Master Career Record"
WEBSITE_REPO_ENV = "QUINTACLE_WEBSITE_REPO"
WEBSITE_CONTENT_ENV = "QUINTACLE_WEBSITE_CONTENT_DIR"
DEFAULT_CONTENT_DIR = "frontend/public/content"


class CareerState:
    def __init__(self, data_dir: Path):
        self.dir = Path(data_dir) / "career"

    def _read(self, name: str) -> dict:
        path = self.dir / name
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    def _write(self, name: str, data: dict) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.dir / f".{name}.tmp"
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.dir / name)

    # --- settings ---------------------------------------------------------

    def settings(self) -> dict:
        s = self._read("settings.json")
        return {
            "record_folder": s.get("record_folder")
            or os.environ.get("QUINTACLE_CAREER_RECORD_FOLDER", "").strip()
            or DEFAULT_RECORD_FOLDER,
            "record_title": s.get("record_title")
            or os.environ.get("QUINTACLE_CAREER_RECORD_TITLE", "").strip()
            or DEFAULT_RECORD_TITLE,
            "website_repo": str(website_repo()),
            "website_content_dir": website_content_dir(),
        }

    def update_settings(self, record_folder: str | None, record_title: str | None) -> dict:
        s = self._read("settings.json")
        if record_folder is not None:
            s["record_folder"] = record_folder.strip()
        if record_title is not None:
            s["record_title"] = record_title.strip()
        self._write("settings.json", {k: v for k, v in s.items() if v})
        return self.settings()

    # --- website ----------------------------------------------------------

    def website(self) -> dict:
        w = self._read("website.json")
        w.setdefault("watermark", None)
        w.setdefault("last_run", None)
        w.setdefault("rejected", {})
        w.setdefault("entry_hashes", {})
        w.setdefault("last_result", None)
        return w

    def save_website(self, data: dict) -> None:
        self._write("website.json", data)


def website_repo() -> Path:
    raw = os.environ.get(WEBSITE_REPO_ENV, "").strip()
    return Path(raw).expanduser() if raw else Path.home() / "code" / "PersonalWebsite"


def website_content_dir() -> str:
    return os.environ.get(WEBSITE_CONTENT_ENV, "").strip().strip("/") or DEFAULT_CONTENT_DIR
