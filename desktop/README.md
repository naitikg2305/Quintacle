# Quintacle desktop shell

The pywebview desktop shell `docs/stack.md` decided on: one native window, one
process, no browser tab. Targets Linux and Windows.

## How it works — one port, zero CORS

`desktop/app.py` builds a wrapper FastAPI app: it takes the untouched core app
from `quintacle_core.api.create_app()` and *additionally* mounts the
frontend's static export (`frontend/out/`) at `/` via `StaticFiles(html=True)`.
API routers are registered first, so API routes always win; the static UI only
catches paths no route claimed. UI and API therefore share one origin —
`http://127.0.0.1:8000` — which also matches the `API_BASE` default baked into
the static bundle (`frontend/lib/api.ts` defaults to `http://localhost:8000`),
so even that absolute URL resolves to the same server. No CORS, nothing in
`core/quintacle_core/api.py` modified.

Once the server thread answers `/kb/folders` (polled, not slept-on), pywebview
opens a 1280x860 window titled "Quintacle" on it. Closing the window exits the
process cleanly.

**Single instance:** before starting a server the shell probes port 8000.
If `/kb/folders` answers with a JSON list, a Quintacle backend is already
running — the shell skips starting another and just opens the window onto it.
If the port is held by anything else, it exits with a readable message naming
the port.

## Running

```bash
# from the repo root, with core/.venv set up:
core/.venv/bin/pip install -r core/requirements.txt -r desktop/requirements.txt

core/.venv/bin/python desktop/app.py            # the app window
core/.venv/bin/python desktop/app.py --dev      # window on http://localhost:3000
                                                # (live `npm run dev` frontend)
core/.venv/bin/python desktop/app.py --smoke    # headless CI/sandbox check:
                                                # server up, /kb/folders AND /
                                                # answer 200, print OK, exit 0
```

The non-`--dev` window needs the static export to exist:

```bash
cd frontend && npm install && CAPACITOR_BUILD=true npx next build   # -> frontend/out/
```

`--smoke` always starts its own server (reusing whatever sits on :8000 would
verify that server, not this build); if :8000 is busy it falls back to an
ephemeral port, which is fine because no UI is opened in smoke mode.

## Environment (`.env`) resolution

The core reads `ANTHROPIC_API_KEY` etc. via python-dotenv from `core/.env`
*relative to its cwd* — a packaged binary's cwd is wherever the user launched
it, so that lookup can't be relied on. The shell therefore loads env files
explicitly, before `quintacle_core` is imported, in this precedence order
(python-dotenv never overrides already-set variables):

1. real process environment
2. `~/.quintacle/.env` — **the packaged-app convention**; put your keys here
3. `core/.env` — repo-checkout fallback (source runs only)

Data lives in `~/.quintacle/` as usual; override with `QUINTACLE_DATA_DIR`.

## pywebview backend choice

- **Linux: Qt (`pywebview[qt]`, forced via `webview.start(gui="qt")`).**
  Verified in this repo's sandbox: `pip install "pywebview[qt]"` pulls QtPy +
  PyQt6 6.11 + PyQt6-WebEngine and `webview.platforms.qt` imports cleanly with
  zero system packages. The GTK/WebKit backend needs distro packages
  (`gir1.2-webkit2`, PyGObject) that pip cannot install, which would make the
  PyInstaller bundle depend on the host system. Qt is fully pip-installable
  and PyInstaller-bundleable — the pragmatic choice. Cost: QtWebEngine is a
  bundled Chromium, so the Linux bundle is large (~645 MB, of which ~456 MB is
  PyQt6/QtWebEngine).
- **Windows: WebView2** (preinstalled on Windows 10/11) via plain `pywebview` —
  nothing to bundle beyond the wheel, hence the tiny expected Windows artifact.

## Packaging

### Linux (verified here)

```bash
cd frontend && CAPACITOR_BUILD=true npx next build && cd ..
core/.venv/bin/pyinstaller desktop/quintacle.spec --noconfirm
QUINTACLE_DATA_DIR=$(mktemp -d) dist/quintacle/quintacle --smoke   # must print OK
desktop/install-linux.sh    # -> ~/.local/opt/quintacle, ~/.local/bin/quintacle,
                            #    ~/.local/share/applications/quintacle*.desktop
```

Spec decisions (see comments in `quintacle.spec`):
- **opencv (`cv2`) is excluded** — it's ~60 MB and only powers frame sampling
  for AI video descriptions on KB drop; `kb/drop.py` imports it lazily and
  returns no frames on `ImportError`, so packaged builds lose only the
  video-description feature (videos still save). numpy (cv2's dep, unused
  elsewhere) is excluded too. **Pillow is bundled** (image handling everywhere).
- `console=True` so `--smoke` output and startup errors stay visible; on
  Windows that means a console window behind the app — flip once mature.
- `frontend/out/` ships as the `frontend_out` data dir
  (`sys._MEIPASS/frontend_out` at runtime).

### Windows (unverified — built by CI only)

PyInstaller does not cross-compile; a Windows `.exe` cannot be built on Linux.
`.github/workflows/desktop.yml` builds both OSes on tag push (`v*`) or manual
dispatch: static export → pip install → PyInstaller → run the artifact's
`--smoke` (headless, works on both runners) → upload artifacts. The YAML is
syntax-checked but has **never executed in Actions** — watch the first run.

## Interim launcher (daily driver, zero packaging)

`desktop/launch-dev.sh` starts the backend on :8000 if nothing Quintacle-shaped
answers there, starts/reuses the `npm run dev` frontend on :3000, then opens
`chromium --app=http://localhost:3000` (falls back to `google-chrome-stable`).
`install-linux.sh` also installs its launcher entry ("Quintacle (dev)").
Logs land in `~/.quintacle/logs/`.

## Tests

```bash
core/.venv/bin/pytest desktop/tests -q    # port-probe + env-resolution logic
cd core && .venv/bin/python -m pytest -q  # full core suite stays green
```

## Known-unverified

- A real window on a display (this was built in a headless sandbox; `--smoke`
  and the Qt import are verified, the actual GUI run is not).
- The Windows build and both CI legs of `desktop.yml`.
- The packaged Qt bundle on distros other than the build machine.
