"""Dependency-light tests for the desktop shell's pure logic.

Run with the core venv's pytest from the repo root:
    core/.venv/bin/pytest desktop/tests -q

Nothing here opens a window or starts uvicorn; the end-to-end check is
`python desktop/app.py --smoke`.
"""

import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app as shell  # desktop/app.py


# --- looks_like_quintacle fingerprint ----------------------------------------

def test_fingerprint_accepts_json_list():
    assert shell.looks_like_quintacle(200, b'["Health", "Finance"]')
    assert shell.looks_like_quintacle(200, b"[]")


def test_fingerprint_rejects_non_quintacle_responses():
    assert not shell.looks_like_quintacle(200, b'{"not": "a list"}')
    assert not shell.looks_like_quintacle(200, b"<html>some other app</html>")
    assert not shell.looks_like_quintacle(404, b"[]")
    assert not shell.looks_like_quintacle(200, b"\xff\xfe garbage")


# --- probe_port classification -------------------------------------------------

def test_probe_free_port():
    with socket.socket() as sock:
        sock.bind((shell.HOST, 0))
        port = sock.getsockname()[1]
    # closed again -> nothing listens there
    assert shell.probe_port(shell.HOST, port) == "free"


class _Handler(BaseHTTPRequestHandler):
    payload = b"[]"
    status = 200

    def do_GET(self):  # noqa: N802 — http.server API
        self.send_response(self.status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(self.payload)

    def log_message(self, *args):
        pass


def _serve(payload: bytes, status: int = 200):
    handler = type("H", (_Handler,), {"payload": payload, "status": status})
    server = HTTPServer((shell.HOST, 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def test_probe_detects_quintacle():
    server = _serve(b'["Health"]')
    try:
        assert shell.probe_port(shell.HOST, server.server_address[1]) == "quintacle"
    finally:
        server.shutdown()


def test_probe_detects_other_http_service():
    server = _serve(b"<html>definitely not quintacle</html>")
    try:
        assert shell.probe_port(shell.HOST, server.server_address[1]) == "other"
    finally:
        server.shutdown()


def test_probe_detects_non_http_listener():
    with socket.socket() as sock:
        sock.bind((shell.HOST, 0))
        sock.listen(1)  # accepts TCP but never speaks HTTP
        assert shell.probe_port(shell.HOST, sock.getsockname()[1]) == "other"


# --- env resolution --------------------------------------------------------------

def test_env_candidates_prefers_packaged_convention():
    candidates = shell.env_candidates()
    assert candidates[0] == Path.home() / ".quintacle" / ".env"
    # In a repo checkout (unfrozen), core/.env is the fallback.
    assert candidates[1] == shell.repo_root() / "core" / ".env"


def test_frontend_out_dir_in_source_checkout():
    assert shell.frontend_out_dir() == shell.repo_root() / "frontend" / "out"
