# Quintacle as a real Android APK, no PC needed

Status: **backend-bootstrap half written, not yet verified on a real
device.** The Termux setup/migration/persistence scripts described in step
6 below now exist — see `scripts/termux/` and
`docs/termux-backend-setup.md` for the concrete, runnable version of that
step. They were written and syntax-checked (plus the data-migration pair
round-trip tested) in an environment without a physical Android device
attached, so "should work per Termux's documented package manager and
APIs" is the honest claim, not "tested on-device." The Capacitor/frontend
half (steps 1-5, 7) is separate work, not covered here.

> **Status update 2026-10-15: scaffolded, not yet an APK.** Both halves are
> now committed: the Capacitor project exists (`frontend/android/`, a real
> Gradle project, with the `CAPACITOR_BUILD=true` static export building all
> pages) *and* the Termux scripts (`scripts/termux/`). What remains is
> exactly the device-side tail: `gradlew assembleDebug` needs JDK17 + the
> Android SDK (or the phone itself), and nothing has ever run on a real
> device — Termux backend included. The exact remaining steps, in order, are
> in `reference/android.md`. Also note the cv2 risk in step 6 below is
> **stale** — see the dated correction there.

## Why

The goal from the start of this build was a "no PC needed" architecture —
using Quintacle entirely from the phone, without depending on a laptop/
desktop being on. The user already has Termux installed and explicitly wants
a real installed APK, not a browser bookmark/PWA shortcut.

Checked the codebase before planning this: the Next.js frontend
(`frontend/`) has zero server-side-only features anywhere — no
`middleware.ts`, no `app/api/*` routes, no `generateStaticParams`, no
`export const dynamic`. Every page is a `"use client"` component that talks
to the FastAPI backend exclusively through `frontend/lib/api.ts`'s
`fetch(...)` calls. This means the frontend can be built as a **static
export** (plain HTML/CSS/JS, no Node server required at runtime) and bundled
directly into a native app shell — wrapping what's already built, not
rewriting it. The FastAPI backend (all the actual domain logic — LLM
routing, the ~15 entry-type stores, the deterministic drop pipeline) stays
100% untouched.

Environment check on the dev machine (Arch Linux, 108GB free): Node 26/npm
12 already installed (fine for Capacitor); no JDK, Android SDK, or `adb` yet
— all installable via `pacman`, no blockers found.

## Architecture decision: Capacitor, not a Trusted Web Activity

Considered wrapping this as a TWA (Bubblewrap) instead, since that's the
other common "turn a web app into an APK" path — ruled out because a TWA
expects the app to be served from a real HTTPS domain with a verified
`assetlinks.json`, which doesn't fit a fully local, on-device, no-domain app
at all. **Capacitor** is the right fit: it bundles the static frontend
directly into the APK (no domain, no HTTPS server needed for the UI itself),
and the app's own JS makes plain `fetch()` calls to `http://localhost:8000`
for the API — which correctly resolves to *the same phone* once both the app
and the Termux-hosted backend run on-device. This sidesteps the LAN-IP
problem entirely (that only mattered for the earlier-discussed PC+phone-
over-WiFi scenario).

**Split of responsibilities:**
- **Inside the APK**: the static-exported Next.js UI (Capacitor's WebView
  shell). No Node process needed on the phone at all.
- **In Termux**: only the Python FastAPI backend, bound to `127.0.0.1:8000`
  (loopback-only — nothing outside the phone needs to reach it, more secure
  than the current dev setup too). The user's real `~/.quintacle` data gets
  copied onto the phone so the Termux backend starts with actual data, not
  empty (confirmed directly: migrate real data, don't start fresh).

## Implementation steps

1. **Frontend static export** — `frontend/next.config.ts` gets
   `output: "export"`. Run `next build`, spot-check the static output for a
   couple of pages (e.g. `/kb/drop`, `/documents`) to confirm nothing broke
   (`images: { unoptimized: true }` needed if `next/image` is ever used —
   not currently the case, worth reconfirming at build time).

2. **Capacitor scaffolding**, inside `frontend/`:
   - `npm install @capacitor/core @capacitor/cli @capacitor/android`
   - `npx cap init` (app name "Quintacle", package id e.g.
     `com.naitikg.quintacle`), `npx cap add android` — creates
     `frontend/android/`, a real native Gradle project.
   - `capacitor.config.ts` points `webDir` at the static export output
     (`out/` by default for `next export`).

3. **Android network security config** — add
   `android/app/src/main/res/xml/network_security_config.xml` allowing
   cleartext traffic to `localhost`/`127.0.0.1` (Android blocks plaintext
   HTTP by default on recent API levels; loopback-only HTTP is fine here, no
   cert needed).

4. **Build tooling** — `pacman -S jdk17-openjdk android-tools` (JDK +
   `adb`), plus Google's Android command-line SDK tools (just the
   `sdkmanager`-installable platform/build-tools — not full Android Studio,
   not needed just to build/sign an APK from the CLI).

5. **Build the APK** — `./gradlew assembleDebug` inside `frontend/android/`.
   Debug-signing is fine for personal sideloading (no Play Store involved);
   produces a real installable `.apk`.

6. **Termux backend setup** — now written as exact scripts + instructions,
   see `docs/termux-backend-setup.md` and `scripts/termux/`:
   - `scripts/termux/setup.sh` — `pkg install`s Python plus Termux-prebuilt
     native deps (Pillow, numpy, opencv, lxml — pip source-builds of these
     are impractical/unreliable on Termux's Bionic libc, detailed in the
     doc), then pip-installs the rest of `core/requirements.txt` into a
     `--system-site-packages` venv. Flags `pydantic-core` (Rust build,
     ~10 min first time) and `opencv-python` (no guaranteed prebuilt
     package on every Termux repo mirror — and notably, `cv2` is imported
     at module load time in `kb/drop.py`, so if it's missing the *whole*
     API fails to start, not just video-drop handling) as the two real
     risk points. *(2026-10-15 correction: the cv2 half of that is stale —
     `cv2` is lazy-imported now, commit `e105b69` 2026-10-13, so a missing
     `cv2` only disables video drops; the API boots without it.)*
   - `scripts/termux/migrate-export.sh` (desktop) /
     `migrate-import.sh` (Termux) — tarball-based one-time copy of the real
     `~/.quintacle` onto the phone (chosen over the LAN-sync mechanic in
     `deployment-and-privacy.md`, which is designed for two already-running
     copies diffing an existing shared file, not a cold first seed).
   - `scripts/termux/start-backend.sh` — runs
     `uvicorn quintacle_core.api:app --host 127.0.0.1 --port 8000` with a
     restart-on-crash loop and `termux-wake-lock`.
   - `scripts/termux/install-boot-autostart.sh` — wires
     `scripts/termux/start-backend.sh` into `~/.termux/boot/`. Installing
     the Termux:Boot app itself, opening it once, and exempting Termux from
     battery optimization are manual, physical-device steps that can't be
     scripted — spelled out in `docs/termux-backend-setup.md`.

7. **Hand off the `.apk`** — transferred to the phone (cable/cloud/`adb
   install` if connected via USB) and sideloaded ("install unknown apps"
   enabled for the source). This install step happens on the physical
   device, outside what a coding session can do directly.

## Explicitly out of scope for this pass

- Play Store distribution / proper release signing — not needed for personal
  sideload use.
- A configurable/remote API base URL (pointing the app at a non-Termux
  backend later) — will hardcode `http://localhost:8000`, matching the
  actual "fully local, on-device" use case. Easy to add later if ever
  wanted.
- Real app icon/branding — a placeholder icon gets used; swappable later.

## Verification (when this gets picked up)

- `next build` with static export completes with no errors; spot-check 2-3
  built pages render correctly when served statically (e.g. via
  `npx serve out/`) before wrapping in Capacitor.
- `./gradlew assembleDebug` succeeds and produces a real `.apk` file.
- Exact Termux commands documented so the user can run them and confirm
  `curl http://127.0.0.1:8000/documents` works from within Termux before
  trying the app.
- After install: confirm the app loads the UI (bundled static assets) and
  successfully round-trips a real API call (e.g. the Documents or People
  list populates from the migrated data) — done by the user, since a coding
  session can't drive their physical device.
