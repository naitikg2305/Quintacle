# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Quintacle desktop shell.

Build (from the repo root, with core/.venv carrying both requirement sets):
    cd frontend && CAPACITOR_BUILD=true npx next build && cd ..   # frontend/out/
    core/.venv/bin/pyinstaller desktop/quintacle.spec --noconfirm

Produces a onedir bundle at dist/quintacle/ (entry point dist/quintacle/quintacle).
Verify it headlessly with:
    QUINTACLE_DATA_DIR=$(mktemp -d) dist/quintacle/quintacle --smoke

Notes:
- opencv (cv2) is EXCLUDED on purpose: it is ~60 MB and only powers frame
  sampling for video descriptions in KB drop (core/quintacle_core/nodes/kb/
  drop.py imports it lazily and degrades gracefully — videos still save, they
  just get no AI description). Pillow IS bundled (image handling everywhere).
- numpy is excluded too; nothing in the core uses it except cv2.
- frontend/out/ is bundled as the `frontend_out` data directory; desktop/app.py
  looks for it at sys._MEIPASS/frontend_out when frozen.
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

spec_dir = Path(SPECPATH).resolve()  # noqa: F821 — SPECPATH injected by PyInstaller
repo_root = spec_dir.parent

frontend_out = repo_root / "frontend" / "out"
if not frontend_out.is_dir():
    raise SystemExit(
        f"frontend static export missing at {frontend_out} — run "
        "`cd frontend && npm install && CAPACITOR_BUILD=true npx next build` first"
    )

hiddenimports = (
    collect_submodules("quintacle_core")
    + collect_submodules("uvicorn")
    + collect_submodules("webview")
)

a = Analysis(
    [str(spec_dir / "app.py")],
    pathex=[str(repo_root / "core")],
    binaries=[],
    datas=[(str(frontend_out), "frontend_out")],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["cv2", "numpy"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="quintacle",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # console=True keeps --smoke output visible (and startup errors
    # debuggable) on every platform; on Windows this means a console window
    # opens behind the app. Flip to console=False once the Windows build is
    # mature, or ship two exes.
    console=True,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="quintacle",
)
