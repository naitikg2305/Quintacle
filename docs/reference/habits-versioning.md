# Habits versioning — how it works

Code-derived 2026-10-20 (next-wave-plan §8). Restamp if regenerated.
Code: `core/quintacle_core/db.py`, `core/quintacle_core/nodes/logs/{repository,quotas,api}.py`;
tests: `core/tests/test_habit_versions.py`.

## The model

- **`habits` is identity only**: `id`, `name` (UNIQUE), `ended_on`
  (NULL = live; a date = the last day the habit is still judged). The legacy
  value columns (`target_amount` …) remain physically and still receive the
  latest values on create (they're NOT NULL), but nothing reads them —
  `habit_versions` is the only source of targets.
- **`habit_versions`** holds every target shape the habit has ever had:
  `habit_id`, `effective_from` (ISO date — the period start this version
  takes force), `target_amount`, `target_period`, `match_category`, `unit`,
  `metric`, `direction`, `match_kind`, `created_at`. Append-only; ties on
  `effective_from` resolve to the highest id (latest edit wins), earlier
  rows stay as history. Index on `(habit_id, effective_from)`.
- **Migration/backfill** (idempotent, in `db._MIGRATIONS`): adds
  `habits.ended_on`, then inserts one version per legacy habit with
  `effective_from = '0001-01-01'` — in force since forever. Pre-versioning
  weeks are therefore judged against the targets current at migration time:
  the only honest reading, since no edit history exists before this wave.

## Activation semantics (the exact rules shipped)

- **New habit** (`add_habit`, new name): first version effective at the
  CURRENT period's start — a habit added Thursday counts this week.
- **Edit** (upsert by existing name, or `PATCH`): appends a version
  effective at the NEXT boundary of the NEW version's own period — week /
  2weeks → next Monday (2weeks has no natural anchor; next Monday is the
  convention), month → the 1st of next month, day → tomorrow
  (`quotas.next_period_start`). The current period finishes under the old
  target. Because a version's `effective_from` always sits on its own
  period's grid, a week→month edit made Oct 22 activates Nov 1 (not a
  Monday), and every era's windows align cleanly with the version that owns
  them. PATCH merges the given fields over the habit's LATEST version
  (pending included), so same-week edits compose; explicit `null` clears
  the nullable matcher fields.
- **End** (`DELETE` → `end_habit`): `ended_on` = the current period's last
  day — the period in progress is still judged (symmetric with
  edit-takes-effect-next-period). The row and all versions are never
  deleted. Re-`add_habit` of an ended name clears `ended_on` and appends a
  next-period version — same identity, history intact.
- **Judging**: a window is owned by whichever version was in force at its
  START — a week by its Monday, a month by its 1st
  (`repository.version_in_force(habit_id, window_start)`).

## Reads

- **`GET /logs/habits`** — identity ⋈ version-in-force-today flattened to
  the pre-versioning shape, plus additive keys: `ended_on`,
  `effective_from`, `pending` (the not-yet-active latest version as a dict,
  or null). End-dated habits keep appearing until `ended_on` passes.
- **`/logs/habits/{id}/progress`** — the current window under the version
  in force at its start; for an ended habit past `ended_on`, the FINAL
  window, frozen.
- **`/logs/habits/{id}/history`** — steps back per era: each window is
  sized by its own version's `target_period` (weekly windows in the weekly
  era, real-calendar months in the monthly era, the old era's last window
  truncated at the boundary), skips windows before the first
  `effective_from`, starts at `ended_on` for ended habits. Response shape
  unchanged (per-point `target` was already there — the dashboard Sparkline
  needed zero changes).
- **`GET /logs/habits/ledger?weeks=N`** (`quotas.weekly_ledger`) — the
  goals-calendar feed:

  ```
  {
    "weeks":  [{start, end} … oldest first, last = current partial week],
    "habits": [{id, name, unit, metric, direction, cells: [
        {window: {start, end}, target, actual, met, in_progress,
         elapsed_days, period_days, prorated_target, effective_from,
         active, days_met?, days_total?}
    ]}]
  }
  ```

  One cell per Monday-anchored week-column × habit, judged under the
  version in force on that Monday; month-period cells carry their real
  containing month window; 2weeks cells anchor to the cell's Monday
  (rolling windows have no grid); day-period habits aggregate the week's
  day-windows into `days_met`/`days_total`. `in_progress` is true only
  while measurement can still move (the cut-off was today, not a passed
  `ended_on`). `active:false` before the first `effective_from` and after
  `ended_on`; habits with no active cell in the range are dropped from the
  response. Everything is SQL/code — the client only formats.

## Writes (gating)

Same as before this wave: habit writes are explicit user actions on the
Habits page (POST/PATCH/DELETE through `nodes/logs/api.py`); the drop/chat
`habit:` lane (separate §8 build) goes through the drop review gate before
calling the same POST.

## Metrics

`activity_hours`, `food_kcal`, `spend` (budget-line matcher), and — new this
wave — `exercise_days`: `COUNT(DISTINCT date)` over `exercise_sets`
in-window (`repository.exercise_days_between`), unit "sessions", direction
`at_least`. "Gym 4x/week" is a one-liner now.

## Frontend

- **Habits page** (`frontend/app/habits/page.tsx`; §8 records it as
  eventually retiring — kept minimal): per-card Edit (prefills the form
  from the pending version when one exists; PATCH; status "takes effect
  <date>"), End ("ends <date>" until it passes), pending-version banner,
  upsert-aware add status, and a "Gym days" goal type.
- **Calendar** (`frontend/app/day/page.tsx`): third Segmented tab
  **Habits** — week rows with per-habit status chips (word/icon + tone per
  the GoalStatus convention, never color alone); week click opens the
  Panel/BottomSheet ledger table with target-in-force (effective date shown
  when it differs from the current version), actual, status, and the
  current week's pace line from `prorated_target`/`elapsed_days` —
  formatting only, zero client arithmetic.
- `frontend/lib/date.ts` adds `mondayOfWeek`/`addDaysIso` (UTC field
  arithmetic on the date string — ET-safe, no local `new Date()` math);
  `frontend/lib/api.ts` adds `updateHabit`, `endHabit`, `getHabitsLedger`
  and the `HabitPending`/`LedgerCell`/`LedgerHabit`/`HabitsLedger` types.
