# Android — current state of the phone story

Derived from code at commit `884d057` on 2026-10-15.

The target architecture (docs: `docs/android-apk-migration.md`,
`docs/termux-backend-setup.md`): the same Next.js UI statically exported
and wrapped in a Capacitor APK, talking to the same FastAPI backend running
on the same phone inside Termux at `http://127.0.0.1:8000`. No Play Store,
no cloud, no Node server on-device.

**Honest status: everything is scaffolded and syntax-checked; nothing has
been run on a real device, and no APK has ever been built** (no JDK/Android
SDK in the dev environment). The design docs are explicit about this; the
breakdown below cross-checks their claims against the actual files.

## The Capacitor project (`frontend/`)

- **`capacitor.config.ts`**: `appId com.naitikg.quintacle`, `appName
  Quintacle`, `webDir: 'out'`.
- **`next.config.ts`**: `CAPACITOR_BUILD=true` is the only switch — it adds
  `output: "export"` (plain static HTML/CSS/JS, no Node server). Plain
  `next dev`/`build`/`start` are unaffected.
- **Build pipeline** (`package.json` scripts):
  - `npm run android:build` = `rm -rf out && CAPACITOR_BUILD=true next
    build && cap sync android` — static export into `out/`, then Capacitor
    copies it to `android/app/src/main/assets/public` and syncs plugin
    config.
  - `npm run android:open` = `cap open android` (Android Studio).
- **`frontend/android/`**: a full generated Gradle project (gradlew,
  `app/`, `variables.gradle`, Capacitor settings) committed to the repo.
- **Network security config**
  (`android/app/src/main/res/xml/network_security_config.xml`): permits
  cleartext HTTP to `localhost` and `127.0.0.1` only
  (`includeSubdomains="false"` on both) — Android blocks plaintext HTTP by
  default on API 28+, and loopback traffic to the on-device backend doesn't
  need TLS.
- The API base stays hardcoded `http://localhost:8000` (`lib/api.ts`
  default; `NEXT_PUBLIC_API_BASE` would be baked at export time). A
  configurable/remote base URL is explicitly out of scope for this pass.

## The Termux scripts (`scripts/termux/`)

| Script | Job |
|---|---|
| `setup.sh` | Termux-only (guards on `$PREFIX`): `pkg update/upgrade`, installs Python + rust/binutils (for the `pydantic-core` source build) + Termux-prebuilt native deps (`python-pillow`, `python-lxml`, `opencv-python`, numpy) instead of letting pip build them on Bionic libc; creates a `--system-site-packages` venv at `core/.venv`; pip-installs the rest of `core/requirements.txt`; sanity-checks every import. Idempotent |
| `start-backend.sh` | Runs `uvicorn quintacle_core.api:app --host 127.0.0.1 --port 8000` (port via `QUINTACLE_PORT`, data dir via `QUINTACLE_DATA_DIR`, default `~/.quintacle` — deliberately NOT Android shared storage, because SQLite over the FUSE/scoped-storage mount is unreliable). `--once` = foreground single run; default = restart-on-crash `while true` loop + `termux-wake-lock`. Warns if `core/.env` is missing; runs with cwd `core/` so `load_dotenv()` finds it |
| `boot-autostart.sh` | The Termux:Boot entry point — template with a `__QUINTACLE_REPO_ROOT__` placeholder; backgrounds `start-backend.sh` detached (nohup+disown, since Termux:Boot won't babysit a foreground process) and logs to `~/.quintacle-logs/` |
| `install-boot-autostart.sh` | Writes the template into `~/.termux/boot/start-quintacle` with the real repo path sed-filled in, then prints the three manual steps it cannot do |
| `migrate-export.sh` | Desktop side: tars `~/.quintacle` (fixed `quintacle-data/` top-level dir) → `quintacle-data-<ts>.tar.gz`. A one-time cold seed — deliberately not the LAN-sync mechanic, which needs two already-running backends |
| `migrate-import.sh` | Termux side: unpacks the tarball into `~/.quintacle`; a non-empty existing dir is moved aside to `~/.quintacle.bak-<ts>` (never merged, never overwritten) |

## Verified vs. needs-a-device

Cross-checking `docs/termux-backend-setup.md` + `frontend/README.md`
against the files:

**Actually verified**: scripts written and `bash -n` syntax-checked; the
migrate export/import pair round-trip tested on a regular Linux box; the
Capacitor/Gradle scaffolding and network config exist as described.

**Never verified (no device/JDK was attached)**: every Termux-specific step
— `pkg` package availability per mirror (the docs flag `opencv-python` as
the riskiest and `pydantic-core`'s ~10-minute Rust build as the slowest),
the wake-lock/Termux:Boot chain, SQLite behavior, the static export's
runtime behavior inside a WebView, and the APK build itself.

**One stale doc claim worth knowing** (the docs vs. the code today): both
`docs/termux-backend-setup.md` ("If `opencv-python` won't install") and
`docs/android-apk-migration.md` say `kb/drop.py` imports `cv2` at module
load time, so a missing OpenCV would prevent the whole API from starting,
and propose moving the import into the one function that uses it as a
future fix. **That fix has since been made**:
[nodes/kb/drop.py](../../core/quintacle_core/nodes/kb/drop.py)'s
`_extract_video_frames` imports cv2 lazily inside the function and returns
`[]` on ImportError — a missing cv2 now only disables video-frame
captioning, not the API. The docs' troubleshooting advice on this point is
out of date (in the safe direction).

Also inherently manual, listed so nothing is silently skipped: installing
the Termux:Boot and Termux:API companion apps (F-Droid), opening
Termux:Boot once (Android requires a first manual launch before
`BOOT_COMPLETED` delivery), `termux-setup-storage`, exempting Termux from
battery optimization (plus any OEM-skin autostart toggle), and one real
reboot to confirm the chain.

## Exact remaining steps to a running APK

1. On a machine with Node: `cd frontend && npm run android:build` — confirm
   the static export completes and spot-check `out/` pages (e.g.
   `npx serve out`).
2. With a JDK + Android SDK: `cd frontend/android && ./gradlew
   assembleDebug` — debug signing is fine for personal sideloading.
3. Sideload the APK (`adb install`, or copy + "install unknown apps").
4. On the phone: get the repo into Termux, run `scripts/termux/setup.sh`,
   create `core/.env` with `ANTHROPIC_API_KEY` (+`OPENAI_API_KEY` if GPT/
   image-gen is wanted).
5. Seed data: `migrate-export.sh` on the desktop → transfer → 
   `migrate-import.sh` in Termux.
6. `bash scripts/termux/start-backend.sh --once`; confirm
   `curl http://127.0.0.1:8000/documents` returns real data.
7. Wire reboot survival: `install-boot-autostart.sh` + the manual
   Termux:Boot/battery steps above; reboot once and check
   `~/.quintacle-logs/boot.log` / `backend.log`.
8. Open the app; confirm the UI loads from bundled assets and a real API
   round trip populates (Documents/People lists).
9. Day-to-day thereafter: the LAN sync page keeps phone and desktop
   converged ([sync.md](sync.md)).
