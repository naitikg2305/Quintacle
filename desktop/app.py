#!/usr/bin/env python3
"""Quintacle desktop shell — one window, one process, one port.

Wraps the existing FastAPI core (``quintacle_core.api.create_app()``) and
additionally mounts the frontend's static export (``frontend/out/``) at ``/``,
so UI and API share a single origin on http://127.0.0.1:8000 — no CORS, and
the ``API_BASE`` default already baked into the static bundle
(``http://localhost:8000``) resolves to the same server. The core itself is
never modified: API routes are registered first, so they always win over the
static mount.

Modes:
    python desktop/app.py            native pywebview window on the static UI
    python desktop/app.py --dev      window points at the live `npm run dev`
                                     frontend (http://localhost:3000) instead
    python desktop/app.py --smoke    headless check: start the server, assert
                                     /kb/folders and / both answer 200, print
                                     OK, exit 0. No window — CI/sandbox safe.

See desktop/README.md for packaging and environment details.
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import threading
import time
import urllib.request
from pathlib import Path

HOST = "127.0.0.1"
PORT = 8000
DEV_URL = "http://localhost:3000"
WINDOW_TITLE = "Quintacle"
WINDOW_WIDTH = 1280
WINDOW_HEIGHT = 860
READY_TIMEOUT = 30.0  # seconds to wait for the backend thread to come up

# The endpoint used both as the readiness probe and the "is this Quintacle?"
# fingerprint: cheap, GET, returns a JSON list on any Quintacle backend.
PROBE_PATH = "/kb/folders"


# --- paths ------------------------------------------------------------------

def is_frozen() -> bool:
    """True when running from a PyInstaller bundle."""
    return getattr(sys, "frozen", False)


def repo_root() -> Path:
    """Repo checkout root (desktop/'s parent). Only meaningful unfrozen."""
    return Path(__file__).resolve().parent.parent


def frontend_out_dir() -> Path:
    """Where the static UI export lives.

    Frozen: bundled by quintacle.spec as the `frontend_out` data directory.
    Source: the repo's frontend/out (built via CAPACITOR_BUILD=true next build).
    """
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS")) / "frontend_out"
    return repo_root() / "frontend" / "out"


def env_candidates() -> list[Path]:
    """.env files to load, in precedence order (first file wins per key).

    ~/.quintacle/.env is the packaged-app convention — a bundled binary's cwd
    is wherever the user launched it, so the core's own cwd-relative
    load_dotenv() can't be relied on. In a repo checkout core/.env still
    works as the fallback.
    """
    candidates = [Path.home() / ".quintacle" / ".env"]
    if not is_frozen():
        candidates.append(repo_root() / "core" / ".env")
    return candidates


def load_env() -> None:
    """Load ANTHROPIC_API_KEY etc. before quintacle_core reads os.environ.

    Must run before importing quintacle_core.api: that module resolves
    QUINTACLE_DATA_DIR and calls its own (cwd-relative) load_dotenv() at
    import time. python-dotenv never overrides variables that are already
    set, so real environment > ~/.quintacle/.env > core/.env.
    """
    from dotenv import load_dotenv

    for env_file in env_candidates():
        if env_file.is_file():
            load_dotenv(env_file)


# --- app assembly -----------------------------------------------------------

def build_app():
    """Core FastAPI app + the static UI mounted at / on the same origin."""
    load_env()
    if not is_frozen():
        core_dir = str(repo_root() / "core")
        if core_dir not in sys.path:
            sys.path.insert(0, core_dir)

    from fastapi.staticfiles import StaticFiles
    from quintacle_core.api import create_app

    app = create_app()

    out_dir = frontend_out_dir()
    if out_dir.is_dir():
        # Mounted after every API router is registered, so API routes always
        # win; the static UI only catches paths no API route claimed.
        # html=True serves index.html for / and folder paths.
        app.mount("/", StaticFiles(directory=str(out_dir), html=True), name="ui")
    else:
        print(
            f"warning: static UI not found at {out_dir} — serving API only.\n"
            "  Build it with: cd frontend && CAPACITOR_BUILD=true npx next build",
            file=sys.stderr,
        )
    return app


# --- port probing / readiness ------------------------------------------------

def http_get(url: str, timeout: float = 3.0) -> tuple[int, bytes]:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read()


def looks_like_quintacle(status: int, body: bytes) -> bool:
    """True when a PROBE_PATH response matches Quintacle's fingerprint."""
    if status != 200:
        return False
    try:
        return isinstance(json.loads(body), list)
    except (ValueError, UnicodeDecodeError):
        return False


def probe_port(host: str = HOST, port: int = PORT) -> str:
    """Classify host:port as 'free', 'quintacle', or 'other'."""
    try:
        with socket.create_connection((host, port), timeout=1.0):
            pass
    except OSError:
        return "free"
    try:
        status, body = http_get(f"http://{host}:{port}{PROBE_PATH}")
    except Exception:
        return "other"
    return "quintacle" if looks_like_quintacle(status, body) else "other"


def wait_ready(base_url: str, timeout: float = READY_TIMEOUT) -> bool:
    """Poll the probe endpoint until the server answers (no sleep-and-hope)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            status, body = http_get(f"{base_url}{PROBE_PATH}", timeout=1.0)
            if looks_like_quintacle(status, body):
                return True
        except Exception:
            pass
        time.sleep(0.1)
    return False


def free_port() -> int:
    """Ask the OS for an ephemeral free port."""
    with socket.socket() as sock:
        sock.bind((HOST, 0))
        return sock.getsockname()[1]


# --- server lifecycle ---------------------------------------------------------

def start_server(port: int = PORT):
    """Run uvicorn in a daemon thread; returns (server, thread)."""
    import uvicorn

    app = build_app()
    config = uvicorn.Config(app, host=HOST, port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="quintacle-uvicorn", daemon=True)
    thread.start()
    return server, thread


def stop_server(server, thread) -> None:
    if server is not None:
        server.should_exit = True
        thread.join(timeout=5)


def port_in_use_error() -> str:
    return (
        f"error: port {PORT} on {HOST} is already in use by something that is "
        "not Quintacle.\nStop that process (e.g. `ss -ltnp | grep :"
        f"{PORT}` to find it) and try again."
    )


# --- modes --------------------------------------------------------------------

def run_smoke() -> int:
    """Headless verification: server up, API answers, static UI answers.

    Always starts its own server — reusing a server that happens to be on
    port 8000 would verify that server, not this build. If 8000 is busy
    (e.g. a real Quintacle is running), smoke falls back to an ephemeral
    port; the UI isn't opened in smoke mode, so the port doesn't matter.
    """
    port = PORT if probe_port() == "free" else free_port()
    if port != PORT:
        print(f"note: port {PORT} is busy; smoke-testing on port {port} instead")
    base_url = f"http://{HOST}:{port}"

    server, thread = start_server(port)
    if not wait_ready(base_url):
        stop_server(server, thread)
        print(f"error: backend not ready within {READY_TIMEOUT:.0f}s", file=sys.stderr)
        return 1

    failures: list[str] = []
    try:
        try:
            status, body = http_get(f"{base_url}{PROBE_PATH}")
            if looks_like_quintacle(status, body):
                print(f"smoke: GET {PROBE_PATH} -> {status} (JSON list, "
                      f"{len(json.loads(body))} folders)")
            else:
                failures.append(f"GET {PROBE_PATH} -> {status}, not a JSON list")
        except Exception as exc:
            failures.append(f"GET {PROBE_PATH} failed: {exc}")

        try:
            status, body = http_get(f"{base_url}/")
            if status == 200 and b"<html" in body[:2048].lower():
                print(f"smoke: GET / -> {status} (static index.html, {len(body)} bytes)")
            else:
                failures.append(f"GET / -> {status}, not the static index.html")
        except Exception as exc:
            failures.append(f"GET / failed: {exc}")
    finally:
        stop_server(server, thread)

    if failures:
        for failure in failures:
            print(f"smoke FAILED: {failure}", file=sys.stderr)
        return 1
    print("OK")
    return 0


def run_window(dev: bool) -> int:
    """Start (or reuse) the backend, then open the native window."""
    state = probe_port()
    if state == "other":
        print(port_in_use_error(), file=sys.stderr)
        return 1

    server = thread = None
    if state == "quintacle":
        print(f"reusing the Quintacle server already on port {PORT}")
    else:
        server, thread = start_server()
        if not wait_ready(f"http://{HOST}:{PORT}"):
            stop_server(server, thread)
            print(f"error: backend not ready within {READY_TIMEOUT:.0f}s", file=sys.stderr)
            return 1

    url = DEV_URL if dev else f"http://{HOST}:{PORT}"
    import webview

    webview.create_window(
        WINDOW_TITLE, url, width=WINDOW_WIDTH, height=WINDOW_HEIGHT
    )
    # Linux: force the Qt backend (PyQt6 + QtWebEngine) — fully
    # pip-installable and PyInstaller-bundleable, unlike GTK/WebKit which
    # needs system packages. Windows: pywebview's default picks WebView2.
    gui = "qt" if sys.platform.startswith("linux") else None
    try:
        webview.start(gui=gui)
    finally:
        # Window closed -> webview.start() returns -> clean process exit.
        stop_server(server, thread)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="quintacle",
        description="Quintacle desktop shell: FastAPI core + static UI in one "
        "native window on localhost:8000.",
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help="point the window at the live dev frontend (localhost:3000) "
        "instead of the bundled static UI",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="headless check (no window): start the server, verify "
        f"{PROBE_PATH} and / answer 200, print OK, exit 0",
    )
    args = parser.parse_args(argv)

    if args.smoke:
        return run_smoke()
    return run_window(dev=args.dev)


if __name__ == "__main__":
    sys.exit(main())
