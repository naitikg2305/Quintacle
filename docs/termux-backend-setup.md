# Running the Quintacle backend on-device in Termux

Companion to `docs/android-apk-migration.md` (which covers the Capacitor/
APK half) — this doc is the **backend bootstrap** half: getting
`uvicorn quintacle_core.api:app` running inside Termux, bound to
`127.0.0.1:8000`, with real data, surviving reboots.

Scripts referenced below live in `scripts/termux/`. They were written and
syntax-checked (`bash -n`), and the data-migration pair
(`migrate-export.sh` / `migrate-import.sh`) was round-trip tested on a
regular Linux box, but **none of this has been run inside an actual Termux
session on a real phone** — this was written in an environment with no
Android device attached. Treat the Termux-specific steps as "should work,
based on Termux's documented package manager and APIs," not "verified."
Section "What's manual" below is explicit about what a human has to
physically do on the device regardless.

## 0. Get the repo onto the phone

Pick one:
- `pkg install git openssh` then `git clone` your remote (if you have one
  reachable from the phone), or
- tar up the repo on the desktop and transfer it the same way described in
  step 2 below for the data directory, or
- `pkg install git` + clone from a USB-connected desktop over `adb` port
  forwarding — overkill for a one-time copy, not detailed here.

The scripts assume they're run from inside the repo checkout (they resolve
paths relative to their own location), so it doesn't matter exactly where
on the phone's filesystem the checkout ends up (e.g. `~/quintacle`).

## 1. Install Python + dependencies

```
bash scripts/termux/setup.sh
```

What it does: `pkg install`s Python, a C/Rust build toolchain, and the
Termux-prebuilt versions of the heaviest native dependencies (Pillow,
numpy, opencv, lxml) instead of letting pip try to build them from source;
creates a `--system-site-packages` venv at `core/.venv` so that venv can see
those pkg-installed modules; then pip-installs the rest of
`core/requirements.txt` into it; then sanity-checks every import.

### Dependencies worth knowing about before you run it

Researched via Termux's own GitHub issues/discussions (not hands-on, since
there's no device here) — current as of October 2026:

- **`pydantic` (pulled in by `fastapi`) → `pydantic-core`.** This is a Rust
  extension. There is no prebuilt wheel for Termux's Bionic-libc aarch64
  target on PyPI, so `pip install` falls back to a from-source cargo build.
  This is the single most likely thing to go wrong on a stock Termux
  install. The setup script installs `rust` + `binutils` first specifically
  for this. Expect a genuinely slow first build (real-world reports put it
  around 10 minutes, plus a sizeable one-time download) — don't assume it's
  hung.
- **`opencv-python-headless` → the risky one.** PyPI has no Bionic-libc
  wheel at all, and building OpenCV from source on Termux is reported to
  fail outright on current Android/Termux combinations (missing complex-
  number support in Bionic's math headers trips up numpy's own build
  during OpenCV's configure step). Termux's own package repo ships a
  prebuilt `opencv-python` package (providing the `cv2` module) for exactly
  this reason — the setup script tries `pkg install opencv-python` rather
  than letting pip anywhere near it. **If that pkg isn't available on your
  Termux version/repo mirror, see the callout in the next section — this is
  the one dependency that can block the backend from starting at all.**
- **`Pillow`** — same shape of problem (needs libjpeg/zlib linked
  correctly for Bionic), solved the same way: `pkg install python-pillow`
  instead of `pip install Pillow`.
- **`lxml`** (pulled in by `python-docx`) — same pattern again:
  `pkg install python-lxml`.
- **`anthropic`, `openai`, `fastapi`, `uvicorn` (bare, no `[standard]`
  extra), `python-frontmatter`, `python-dotenv`, `python-multipart`,
  `openpyxl`** — all pure-Python or pull in only pure-Python/already-handled
  dependencies. No special handling expected; flagged here only because
  they weren't singled out above, not because they're risk-free in any
  environment anyone's ever tested this on.

### If `opencv-python` won't install

> *2026-10-15 update: the fix described below **was made** on 2026-10-13
> (commit `e105b69`) — `import cv2` now lives inside the video-frame
> function, so a missing `cv2` only disables video drops; the API boots
> fine without it. The paragraph below is kept as the original analysis, but
> "prevents the entire FastAPI app from starting" is no longer true.*

`core/quintacle_core/nodes/kb/drop.py` does `import cv2` at **module load
time**, and `api.py` imports that module unconditionally. This means a
missing `cv2` doesn't just disable the one feature that actually needs it
(sampling still frames out of a dropped video for vision-LLM captioning) —
**it prevents the entire FastAPI app from starting.** This was flagged
rather than fixed, per this work's scope (not touching app code speculatively
without a real device to confirm against). If you hit this wall for real,
the lowest-risk fix is a one-line change in `drop.py`: move `import cv2`
out of the top-level imports and into the one function that actually uses
it (`cv2.VideoCapture` for video-frame sampling), so a missing `cv2` only
breaks video drops instead of the whole API. That edit is *not* made here —
flagging it precisely so whoever picks this up next doesn't have to
rediscover it from a crash log.

## 2. Migrate your existing data onto the phone

On the **desktop** (wherever your real `~/.quintacle` lives today):

```
bash scripts/termux/migrate-export.sh            # uses ~/.quintacle by default
# -> writes ./quintacle-data-YYYYMMDD-HHMMSS.tar.gz
```

Get that tarball onto the phone. Two options, pick whichever's easier:

- **USB + adb** (most reliable, no network involved):
  ```
  adb push quintacle-data-*.tar.gz /sdcard/Download/
  ```
  then inside Termux, after a one-time `termux-setup-storage` (grants
  Termux access to shared storage — prompts an Android permission dialog,
  can't be scripted):
  ```
  cp ~/storage/shared/Download/quintacle-data-*.tar.gz ~/
  ```
- **Same-WiFi, no USB:** on the desktop, `cd` into the directory with the
  tarball and run `python3 -m http.server 8787`; inside Termux,
  `pkg install curl` then
  `curl -O http://<desktop-LAN-IP>:8787/quintacle-data-*.tar.gz`.

Why not the LAN-sync mechanic from `docs/deployment-and-privacy.md`:
that's designed for two *already-running* copies of the app diffing an
existing shared file, line-by-line, append-only-safe (per that doc's own
caveats, in-place edits/conflicts aren't even fully designed yet). This is
a one-time cold seed onto a phone that has no backend running yet at all —
there's nothing on that side to diff against. A plain one-directional
tarball copy is the right tool for *this specific job* (initial bootstrap);
the LAN sync remains the right mechanic for day-to-day sync once both sides
are actually up and running.

Then, inside Termux:

```
bash scripts/termux/migrate-import.sh ~/quintacle-data-*.tar.gz
```

Defaults to unpacking into `~/.quintacle` (same default the backend itself
uses). If that directory already has anything in it, the script moves it
aside to `~/.quintacle.bak-<timestamp>` first rather than overwriting —
it does not attempt a merge.

**Why `~/.quintacle` and not Android shared storage
(`~/storage/shared/...`):** the backend keeps a live SQLite file in the
data directory (`core/quintacle_core/db.py`). Android's shared storage is a
FUSE-backed, scoped-storage mount — SQLite's file-locking model doesn't
play reliably with that layer on Android (reports of corruption/locking
stalls are common enough to avoid it by default). Termux's own private
home directory is real Linux-native storage, not FUSE, so that's where this
keeps the data.

## 3. Start it and confirm it works

```
cp core/.env.example core/.env   # then edit in ANTHROPIC_API_KEY (and
                                  # OPENAI_API_KEY if you use GPT/image-gen
                                  # features — see core/quintacle_core/
                                  # nodes/kb/api.py and llm_config.py)
bash scripts/termux/start-backend.sh --once
```

In another Termux session (or after backgrounding with `Ctrl-Z; bg`):

```
curl http://127.0.0.1:8000/documents
```

Should return your real migrated data, not an empty list.

## 4. Make it survive reboots and backgrounding

Two separate problems, two separate fixes:

**Problem 1: process needs to restart after a reboot.**
`Termux:Boot` is a *separate companion app* (same maintainers, same
F-Droid/GitHub source as Termux itself) that runs scripts in
`~/.termux/boot/` on `BOOT_COMPLETED`.

```
bash scripts/termux/install-boot-autostart.sh
```

This writes `~/.termux/boot/start-quintacle` (filling in this repo's
on-device path), which backgrounds `scripts/termux/start-backend.sh` (its
own `while true` loop restarts uvicorn if it ever crashes) and logs to
`~/.quintacle-logs/`.

**Problem 2: Android kills/throttles background processes to save
battery**, which would otherwise stop the backend even without a reboot.
`termux-wake-lock` (part of the `termux-api` package, called automatically
by `start-backend.sh`) asks Android to hold a CPU wake lock. This alone
still isn't sufficient on most phones unless you also exempt Termux from
battery optimization — see the manual steps below.

### What's manual here (can't be scripted from a coding session, full stop)

- **Installing the `Termux:Boot` app itself.** Get it from the same source
  as your Termux install (F-Droid strongly recommended for both — the Play
  Store build of Termux is old/unmaintained and often can't talk to add-ons
  installed from F-Droid, a known source of silent failures people hit).
- **Opening Termux:Boot once by hand** after installing it. Android
  requires an app to have been launched at least once by the user before
  it's allowed to receive `BOOT_COMPLETED`. There's no way around this from
  a script.
- **Installing `termux-api` and the companion `Termux:API` app** — same
  deal, needed for `termux-wake-lock`/`termux-wake-unlock` to actually
  work (`pkg install termux-api`, plus installing the Termux:API app from
  the same source).
- **Granting storage access** (`termux-setup-storage`) if you used the
  shared-storage transfer path in step 2 — triggers an Android permission
  dialog that has to be tapped.
- **Exempting Termux (and Termux:Boot) from battery optimization.** Exact
  menu path varies by Android version/OEM skin:
  - Stock Android: Settings → Apps → Termux → Battery → "Unrestricted".
  - MIUI/HyperOS, ColorOS, OneUI, and other heavily-customized skins
    usually have an *additional*, separately-named toggle on top of the
    stock one (e.g. "Autostart", "Allow background activity", "No
    restrictions" under a battery-saver sub-menu) — these OEM battery
    managers are notorious for silently re-killing background apps even
    after the stock Android toggle is set correctly. Check your specific
    phone's settings for anything battery/power-manager-related beyond the
    standard Android menu.
  - If you have `adb` access (USB debugging on, cable or wireless adb
    connected) at setup time, this one step *can* be scripted:
    `adb shell dumpsys deviceidle whitelist +com.termux` (and again for
    `com.termux.boot` if Termux:Boot shows separate battery behavior on
    your device). Not run here since there's no device attached in this
    environment, and it only replaces the stock-Android toggle above, not
    any OEM-specific one.
- **Physically rebooting the phone once** to confirm the whole chain
  actually fires, and checking `~/.quintacle-logs/boot.log` and
  `backend.log` afterward.

None of the above can be done by a script running outside the physical
device — they're listed here so nothing gets silently skipped.

## Troubleshooting

- `curl http://127.0.0.1:8000/...` connection refused → check
  `~/.quintacle-logs/backend.log` (if started via Termux:Boot) or the
  terminal output directly (if run via `--once`) for the actual Python
  traceback — most likely the `cv2` import issue above, or a missing
  `core/.env`.
- Backend starts but every request needing an LLM call 400s → `core/.env`
  is missing or `ANTHROPIC_API_KEY` wasn't filled in.
- `pip install` hangs for a long time with no output during step 1 →
  probably the `pydantic-core` Rust build described above; let it run
  (check `top`/`htop` for an active `rustc`/`cargo` process before assuming
  it's actually stuck).
