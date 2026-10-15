# Seamless mode vs. Admin mode

Status: **design note, build AFTER the full functionality test.** Captured
2026-10-15. The sequencing is deliberate: UI tweaks → test everything on
laptop + phone in the full UI → only then build the seamless face, informed
by what the testing showed.

## The two modes

- **Admin mode = the app as it exists today.** Every page, every knob, the
  manual Sort → review → Save steps, the ledger, the graph, the folder
  browser. This is the testing surface and the power-user surface — it
  never goes away.
- **Seamless mode = the Jarvis face.** A minimal default surface — the
  Drop capture flow (mic/camera/text) plus an agentic chat front — where
  review steps collapse into auto-commit and most chrome disappears.

**Same backend, identical calls.** Seamless mode is not a fork: every
action it takes goes through the exact same REST endpoints (`lib/api.ts`)
the admin UI uses — it just skips confirmation stops and hides pages. The
auto-commit safety story is already built: the MCP-era undo machinery
(staged snapshots + ledger, `mcp-angle.md`) is what makes "just do it" an
acceptable default, because anything auto-committed is visible in a recent-
writes view and reversible.

## The switch

A manual toggle (persisted in localStorage, surfaced somewhere quiet —
Profile or the shell footer). Seamless is the default face once it exists;
flipping to Admin brings the whole cockpit back instantly. One app, one
build, a UI-state flag — no separate deployment, no backend flag.

## How the test run writes the seamless spec

While testing in admin mode, track every manual review/confirm step and
sort it into:

- **Never caught anything** → pure friction → goes auto in seamless mode.
- **Actually caught a misclassification / wrong folder / bad parse** →
  earning its keep → stays manual even in seamless mode (or becomes a
  lightweight "saved — tap to fix" toast instead of a blocking review).

That audit, filled in during the functionality test, IS the seamless-mode
requirements doc. Don't design the seamless UI before it exists.

## Open questions (decide after testing)

- Is seamless mode one page (Drop-with-chat hybrid) or two (capture page +
  chat page), per the original "Ideal" sketch in
  `test-plan-and-wishlist.md`'s architecture section?
- Does seamless mode auto-commit everything, or keep the "saved — undo?"
  toast pattern for AI-classified (vs. prefix-routed) entries?
- Phone defaults to seamless / desktop defaults to admin, or one default
  everywhere?
