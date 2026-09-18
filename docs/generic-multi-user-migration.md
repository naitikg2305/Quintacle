# Generic / multi-user / commercializable Quintacle

Status: **idea, not started.** No code written. To be built (if ever) on a
**separate git branch**, never merged into `main` — same treatment as
`local-inference-migration.md`. `main` stays the personal, hardcoded-to-one-
user build throughout.

## Why this is its own branch, not a toggle

Every structured domain built so far — logs, ingredients/meals, workout
routines, wardrobe/outfits, grooming/routines, documents, home/residences —
is real, hand-written Python: a `store.py`, an `llm.py`, an `api.py` per
domain. None of it is data-driven or configurable. Turning this into
something a *different* person could pick up and use for *their* life is not
a settings flag — it's a different product decision with real trade-offs
worth deciding deliberately, not accidentally inherited from a shortcut taken
today.

## Two different things "generic" could mean — pick one when this gets picked up

**(a) Generic mechanisms, still hand-coded domains.** The actual *patterns* —
deterministic-prefix-then-AI-fallback (`drop_router.py`), a composer that
fuzzy-matches a real library before falling back to AI (meal/outfit/grooming-
routine composition), the `kb_entry` prose fallback with AI-suggested
folders — already work for anyone, no changes needed. What's hardcoded to
this user specifically: `SEED_FOLDERS`, `PREFIX_TYPES`' keyword choices,
category lists (`WARDROBE_CATEGORIES`, `GROOMING_CATEGORIES`, `DOC_TYPES`,
`HOME_CATEGORIES`), fixed home folder paths, `Profile.home_countries`. Making
this usable by someone else at this tier mostly means: turn hardcoded lists
into per-install config/seed data rather than Python constants, keep
everything else as-is. Relatively small.

**(b) A dynamic domain-builder.** AI creates *entirely new structured
stores* on the fly for whatever a new user cares about (a wine collection, car
maintenance, whatever domain they invent) — a real meta-schema system:
dynamically generated Pydantic models, dynamically rendered frontend forms,
a general "define a new collection with these fields" flow instead of a
bespoke Python module per domain. This is a different, much larger
undertaking than (a) — closer to a personal-database platform than an
extension of the current app.

**Not yet decided which of these — or both, staged — this migration means.**
Decide this explicitly before starting, not implicitly by whatever gets
built first.

## What definitely doesn't change if/when this happens

- Markdown-as-source-of-truth, deterministic-first + AI-fallback, and
  approval-before-write are core to what Quintacle *is* — not personal-build
  specifics to strip out for a generic version.
- The KB chat's behavior (per the standing "don't mess with the chat"
  instruction) isn't in scope for this migration either.

## Relationship to `local-inference-migration.md`

Independent axes — local-model inference and multi-user genericization don't
depend on each other, could be tackled in either order or in parallel
branches. Worth remembering both exist as separate, deliberately-deferred
ideas when picking either back up.
