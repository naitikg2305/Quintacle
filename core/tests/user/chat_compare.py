"""Local vs escalated (Claude) chat comparison for the owner's chat tests (2026-11-17).

The owner always asks the local model first, then escalates to Claude. Claude's
answer is the reference ("claude is more accurate ofc. we re trying to save
costs by using the cheaper model. so rely on claudes answer more. have claude
judge it").

Two measures, REPORT ONLY (they never fail a test; the must / must-not checks
in each test stay the pass/fail part):
- similarity: cosine between the two answers' embeddings, from the local
  `embeddinggemma` model (Ollama /api/embed, same model the retrieval index
  uses). 0-1, closeness to Claude's answer, not correctness. Long answers are
  truncated by the embedding model's context.
- facts: Claude (Max only, never the metered API) lists every factual claim in
  the local answer and marks it against its own answer and its knowledge:
  correct / partly / wrong / made_up. Accuracy = correct / (all claims), with
  "partly" counted as half. It also lists what the local answer missed.

Each run writes core/tests/user/reports/<test>-<date>-<time>.md and prints a
one-line summary.
"""
from __future__ import annotations

import json
import math
import re
import urllib.request
from pathlib import Path

REPORTS = Path(__file__).parent / "reports"
JUDGE_MODEL = "opus"

_JUDGE_SYSTEM = """You compare two answers to the same question from a personal assistant app called
Quintacle (so naming Quintacle is not made up; inventing a Quintacle feature is).
The LOCAL answer comes from a small local model. The REFERENCE answer comes from Claude and is
treated as the more accurate one. Judge the LOCAL answer.

1. List every factual claim in the LOCAL answer: numbers, amounts, facts about the world, and claims
   about the user's own data or past chats. Skip greetings, offers and pure opinions.
2. Give each claim one verdict:
   - correct: true, and consistent with the reference (or the reference doesn't cover it but it is true);
   - partly: roughly right but off in a way that matters (a number noticeably too high or low);
   - wrong: false, or contradicts the reference where the reference is right;
   - made_up: refers to something that doesn't exist (a note, a past chat, a number the user never gave).
   If the reference itself is wrong on a point, judge by the facts and say so in "why".
3. List the important points the REFERENCE makes that the LOCAL answer misses.
4. Note any internal contradiction in the LOCAL answer (e.g. totals that don't add up to its own list).
If an EARLIER CONVERSATION is given, it holds an earlier answer from each model. Building on its OWN
earlier answer is fine for either model; judge the facts, and whether the answer does what was asked.

Reply with JSON only, no prose and no code fence:
{"claims": [{"claim": str, "verdict": "correct"|"partly"|"wrong"|"made_up", "correct_value": str, "why": str}],
 "missed": [str], "contradictions": [str], "summary": str}"""


def cosine(a: str, b: str) -> float | None:
    """Cosine of the two answers' embeddings, or None if the embedder isn't reachable."""
    from quintacle_core.nodes.kb.chat import ollama_host
    from quintacle_core.retrieval import embed_model

    payload = {"model": embed_model(), "input": [a, b], "truncate": True}
    req = urllib.request.Request(f"{ollama_host()}/api/embed", data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            e1, e2 = json.load(r)["embeddings"]
    except Exception:
        return None
    dot = sum(x * y for x, y in zip(e1, e2))
    n = math.sqrt(sum(x * x for x in e1)) * math.sqrt(sum(y * y for y in e2))
    return round(dot / n, 3) if n else None


def _history(context: list[dict] | None) -> str:
    """Earlier turns as plain text. In the app both answers to a turn stay in the
    chat (local, then Claude), so a follow-up's context has both."""
    if not context:
        return ""
    turns = [f"[{m.get('label') or m['role']}]\n{m['content'].strip()}" for m in context]
    return "EARLIER CONVERSATION (both models saw this):\n\n" + "\n\n".join(turns) + "\n\n"


def judge(question: str, local: str, reference: str, context: list[dict] | None = None) -> dict:
    """Claude's claim-by-claim verdict on the local answer. Max only: a Max failure
    returns {"error": ...} and never falls back to the metered API. `context` = the
    turns before this question, so a follow-up is judged against what both models saw
    (each model may build on ITS OWN earlier answer)."""
    from quintacle_core.max_backend import MaxError, run as max_run

    user = (f"{_history(context)}QUESTION:\n{question}\n\nLOCAL ANSWER:\n{local}"
            f"\n\nREFERENCE ANSWER (Claude):\n{reference}")
    try:
        text = max_run(_JUDGE_SYSTEM, [{"role": "user", "content": user}], model=JUDGE_MODEL, timeout=600)["text"]
    except MaxError as e:
        return {"error": f"Claude Max unavailable: {e}"}
    m = re.search(r"\{.*\}", text, re.S)
    try:
        return json.loads(m.group(0) if m else text)
    except json.JSONDecodeError:
        return {"error": "the judge didn't return JSON", "raw": text}


def accuracy(verdict: dict) -> float | None:
    claims = verdict.get("claims") or []
    if not claims:
        return None
    score = sum(1.0 if c.get("verdict") == "correct" else 0.5 if c.get("verdict") == "partly" else 0.0
                for c in claims)
    return round(score / len(claims), 2)


def _report(test: str, question: str, local: str, reference: str, sim, verdict: dict, acc) -> str:
    counts: dict[str, int] = {}
    for c in verdict.get("claims") or []:
        counts[c.get("verdict", "?")] = counts.get(c.get("verdict", "?"), 0) + 1
    lines = [f"# {test}: local vs Claude", "",
             f"**Question:** {question.strip()}", "",
             "| Measure | Result |", "|---|---|",
             f"| Similarity to Claude's answer (cosine, 0-1) | {sim if sim is not None else 'n/a (embedder down)'} |",
             f"| Local fact accuracy (Claude-judged) | {f'{acc:.0%}' if acc is not None else 'n/a'} |",
             f"| Claims | " + (", ".join(f"{v} {k}" for k, v in sorted(counts.items())) or "none") + " |", ""]
    if verdict.get("error"):
        lines += [f"**Judge error:** {verdict['error']}", ""]
    if verdict.get("summary"):
        lines += [f"**Verdict:** {verdict['summary']}", ""]
    if verdict.get("claims"):
        lines += ["| Local claim | Verdict | Correct value | Why |", "|---|---|---|---|"]
        for c in verdict["claims"]:
            cell = lambda s: str(s or "").replace("|", "/").replace("\n", " ")
            lines.append(f"| {cell(c.get('claim'))} | {cell(c.get('verdict'))} | {cell(c.get('correct_value'))} | {cell(c.get('why'))} |")
        lines.append("")
    for title, key in (("Missed (in Claude's answer, not in local)", "missed"), ("Contradictions", "contradictions")):
        if verdict.get(key):
            lines += [f"**{title}:**", *[f"- {x}" for x in verdict[key]], ""]
    lines += ["<details><summary>Local answer</summary>", "", local.strip(), "", "</details>", "",
              "<details><summary>Claude answer</summary>", "", reference.strip(), "", "</details>", ""]
    return "\n".join(lines)


def compare(test: str, question: str, local: str, reference: str, context: list[dict] | None = None) -> dict:
    """Run both measures, write the report, print a summary. Never raises on a model failure."""
    from quintacle_core.clock import now

    sim = cosine(local, reference)
    verdict = judge(question, local, reference, context)
    acc = accuracy(verdict)
    REPORTS.mkdir(exist_ok=True)
    path = REPORTS / f"{test}-{now().strftime('%Y-%m-%d-%H%M')}.md"
    path.write_text(_report(test, question, local, reference, sim, verdict, acc), encoding="utf-8")
    acc_s = f"{acc:.0%}" if acc is not None else "n/a"
    print(f"\n{test} local vs Claude: similarity {sim}, local fact accuracy {acc_s} -> {path}")
    return {"similarity": sim, "accuracy": acc, "verdict": verdict, "report": path}
