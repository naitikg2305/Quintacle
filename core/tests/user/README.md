# tests/user — the owner's tests

Built WITH the owner, one feature at a time, from his testing folder
(`~/Desktop/Quintacle Product Testing, files and commands/`). Inputs are his
real files; every expected result is one he stated or confirmed. Nothing
goes in here that he hasn't agreed to.

## How a test is judged (owner, 2026-11-17)

- **Chats are never pass/fail.** They're non-deterministic. Each chat test writes a local vs Claude
  comparison (`chat_compare.py`: similarity + Claude-judged local fact accuracy) to `reports/`.
  T2's older chat expectations are printed as a report, also never failing.
- **Drops are the hard tests**, and only on what the owner stated: the right meal is suggested
  (extra items or extra notes are fine, he deletes them), no food-log card from a meal drop,
  notes in his existing folders, a label read into the right USDA food.
- Anything Claude noticed but the owner never set stays in TESTING-LOG.md as a finding, not a test.
