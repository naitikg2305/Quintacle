# Quintacle — Nightly Check-in + Habit/Quota Tracking

## The nightly ritual

Before sleep, a voice dump or typed dump about the day. Not free-form rambling —
the app prompts specific sections:

- What did I do for work?
- Something productive I did
- Something emotional that happened
- Something fun that happened
- Specific activities (e.g. "golfed today")

This becomes that day's journal entry — same `schedules/<date>/journal.md` slot
from `architecture.md`, just populated by voice/text instead of by media analysis.

## Habit / quota tracking

Goals with different cadences, checked against actual logged activity:

| Habit | Target (examples given) |
|---|---|
| Golf | ~1 hr every 2 weeks |
| Guitar | 2 hrs/month, or framed as 1 hr/week |
| Workout | 1 hr/day -> 7 hrs/week |
| Running | some number of miles (target TBD) |

The system needs to **score** how he's doing against these — did he hit the
weekly/monthly quota or not.

## Consumption logging

Separate from "goals to hit" — these are things to log and be aware of, not
necessarily quotas to reach:

- Alcohol — how much on a specific night
- Smoking — how much
- Vaping — how much

(Open question, not decided: are these meant to have upper-limit targets too —
e.g. "no more than X drinks/week" — or purely observational logging for now?)

## Architectural note: this is the inverse of the March-13 example

`architecture.md`'s worked example was: structured facts already in the store ->
LLM narrates them out to a human. The nightly check-in is the mirror image:

```
messy human input (voice or typed dump)
  -> LLM extracts/normalizes it into structured fields
     (work: ..., productive: ..., emotional: ..., fun: ...,
      golf_minutes: X, workout_minutes: X, drinks: X, cigarettes: X, vape: X)
  -> stored as that day's structured journal entry
  -> (no AI needed from here)
  -> deterministic code tallies against quotas over the relevant time window
     (daily/weekly/biweekly/monthly) and computes a score
```

So the LLM sits at **both edges** of the pipeline — parsing messy input into
structure on the way in, narrating structured output into human language on the
way out — while the middle (storage, quota math, scoring) stays plain
deterministic code. Same principle as `architecture.md`, applied to input instead
of just retrieval.

## Open questions (not decided yet)

- Exact quota targets for running, and whether consumption logs get limits
- How "score" is calculated/displayed (pass/fail per habit? a combined daily/weekly score?)
- Whether missed quotas roll over, reset, or compound (e.g. missed week affects the month)
