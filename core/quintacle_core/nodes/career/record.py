"""The master career record, as text — pure, deterministic, no model.

Format (same one ~/code/TailorCV/backend/tailorcv/record.py parses, kept
compatible on purpose): `## N. Section` periods, `### N.M Title` entries,
labelled blocks inside an entry (`**What I did**`, `**Resume phrasing
bank**`, `**Tech.** ...`), bullets `- text `[TAG]``, `[?]` = unverified.

Two things are added by Quintacle:

- the watermark line `_Covered through: YYYY-MM-DD_` — work logs dated on or
  before that day are already folded in; the next run starts the day after.
  Absent = never run (the UI then asks for a start date).
- appended bullets carry the provenance tag `[WL YYYY-MM-DD]` (work log of
  that date), in the record's backticked tag style.

Writes are APPEND-ONLY: `apply_additions` only ever inserts new lines (and
replaces the single watermark line); every existing line survives, in order.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date

WATERMARK_RE = re.compile(r"^_Covered through:\s*(\d{4}-\d{2}-\d{2})_\s*$", re.MULTILINE)
SECTION_RE = re.compile(r"^##\s+(\d+)\.\s+(.*?)\s*$")
ENTRY_RE = re.compile(r"^###\s+(\d+\.\d+)\s+(.*?)\s*$")
LABEL_RE = re.compile(r"^\*\*([^*]+?)\*\*[.:]?\s*(.*)$")
BULLET_RE = re.compile(r"^\s*-\s+(.*)$")
TAG_RE = re.compile(r"`(\[[^`]*\])`")
# TailorCV only reads entries from these period sections (3-7); new entries
# are only ever created inside them so the record stays parseable there.
ENTRY_SECTIONS = range(3, 8)

PHRASING = "phrasing"
DETAIL = "detail"
SECTION_LABEL = {PHRASING: "Resume phrasing bank", DETAIL: "What I did"}


def watermark_line(d: date | str) -> str:
    return f"_Covered through: {d if isinstance(d, str) else d.isoformat()}_"


def wl_tag(d: date | str) -> str:
    return f"`[WL {d if isinstance(d, str) else d.isoformat()}]`"


@dataclass
class RecordEntry:
    id: str
    title: str  # tags stripped
    section: int
    start: int  # line index of the ### heading
    end: int  # exclusive: first line of the next ##/### heading (or EOF)
    tech: list[str] = field(default_factory=list)


@dataclass
class RecordSection:
    num: int
    title: str
    start: int
    end: int


@dataclass
class ParsedRecord:
    lines: list[str]
    sections: list[RecordSection]
    entries: list[RecordEntry]
    covered_through: date | None

    def entry(self, entry_id: str) -> RecordEntry | None:
        return next((e for e in self.entries if e.id == entry_id), None)

    def entry_text(self, entry_id: str) -> str:
        e = self.entry(entry_id)
        return "\n".join(self.lines[e.start : e.end]) if e else ""

    def entry_hash(self, entry_id: str) -> str:
        return hashlib.sha1(self.entry_text(entry_id).encode("utf-8")).hexdigest()[:16]

    def section(self, num: int) -> RecordSection | None:
        return next((s for s in self.sections if s.num == num), None)


def clean_title(raw: str) -> str:
    return TAG_RE.sub("", raw).strip()


def parse(text: str) -> ParsedRecord:
    lines = text.split("\n")
    sections: list[RecordSection] = []
    entries: list[RecordEntry] = []
    current_section = 0
    for i, line in enumerate(lines):
        if m := SECTION_RE.match(line):
            current_section = int(m.group(1))
            if sections:
                sections[-1].end = i
            if entries and entries[-1].end == -1:
                entries[-1].end = i
            sections.append(RecordSection(current_section, m.group(2).strip(), i, -1))
        elif m := ENTRY_RE.match(line):
            if entries and entries[-1].end == -1:
                entries[-1].end = i
            entries.append(RecordEntry(m.group(1), clean_title(m.group(2)), current_section, i, -1))
    for s in sections:
        if s.end == -1:
            s.end = len(lines)
    for e in entries:
        if e.end == -1:
            e.end = len(lines)
        for line in lines[e.start : e.end]:
            lm = LABEL_RE.match(line)
            if lm and lm.group(1).strip().rstrip(".:") == "Tech":
                e.tech = [TAG_RE.sub("", t).strip().rstrip(".") for t in lm.group(2).split(",") if t.strip()]
                break
    m = None
    for m in WATERMARK_RE.finditer(text):
        pass  # the LAST marker wins if a hand edit left two
    covered = date.fromisoformat(m.group(1)) if m else None
    return ParsedRecord(lines, sections, entries, covered)


def strip_tags(text: str) -> str:
    """Provenance tags out — both the backticked record style and bare
    `[R 2026]` / `[WL ...]` a model might echo back."""
    text = TAG_RE.sub("", text)
    text = re.sub(r"\[(?:R|W|H|N|C|U|WL|\?)[^\]]*\]", "", text)
    return re.sub(r"\s{2,}", " ", text).strip()


def entry_bullets(rec: ParsedRecord, entry_id: str) -> list[dict]:
    """Every bullet in an entry as {text (tags stripped), raw, tags, kind}
    where kind is phrasing/detail/other by the label it sits under."""
    e = rec.entry(entry_id)
    if e is None:
        return []
    out = []
    label: str | None = None
    for line in rec.lines[e.start + 1 : e.end]:
        if lm := LABEL_RE.match(line):
            label = lm.group(1).strip().rstrip(".:")
            continue
        if line.startswith("####") or line.startswith("---"):
            label = None
            continue
        if bm := BULLET_RE.match(line):
            raw = bm.group(1)
            kind = "other"
            if label and label.startswith("Resume phrasing bank"):
                kind = PHRASING
            elif label and (label.startswith("What I") or label.startswith("What Naitik built")):
                kind = DETAIL
            out.append({"text": strip_tags(raw), "raw": raw, "tags": TAG_RE.findall(raw), "kind": kind})
    return out


def _label_matches(label: str, section: str) -> bool:
    if section == PHRASING:
        return label.startswith("Resume phrasing bank")
    return label.startswith("What I") or label.startswith("What Naitik built")


def _last_content_line(lines: list[str], start: int, end: int) -> int:
    """Index of the last line in [start, end) that isn't blank or a `---`
    rule — new blocks go right after it, before the separator."""
    i = end - 1
    while i > start and (not lines[i].strip() or lines[i].strip().startswith("---")):
        i -= 1
    return i


def _insertion_point(lines: list[str], entry: RecordEntry, section: str) -> tuple[int, bool]:
    """(index to insert AFTER, needs_label). The LAST matching labelled list
    in the entry (an entry with "What I did — POS" and "What I did — BI"
    gets new detail bullets under the latter); its last bullet (or the label
    line itself when the list is empty). No such label -> a fresh labelled
    block after the entry's last content line."""
    label_at = None
    for i in range(entry.start + 1, entry.end):
        lm = LABEL_RE.match(lines[i])
        if lm and _label_matches(lm.group(1).strip().rstrip(".:"), section):
            label_at = i
    if label_at is None:
        return _last_content_line(lines, entry.start, entry.end), True
    last = label_at
    i = label_at + 1
    while i < entry.end and not lines[i].strip():
        i += 1  # a blank line between the label and its first bullet
    while i < entry.end and (BULLET_RE.match(lines[i]) or (lines[i].startswith((" ", "\t")) and lines[i].strip())):
        last = i
        i += 1
    return last, False


def bullet_line(text: str, tag_date: str) -> str:
    return f"- {strip_tags(text)} {wl_tag(tag_date)}"


def next_entry_id(rec: ParsedRecord, section_num: int) -> str:
    used = [int(e.id.split(".")[1]) for e in rec.entries if e.section == section_num]
    return f"{section_num}.{max(used, default=0) + 1}"


def apply_additions(
    text: str,
    bullets: list[dict],
    new_entries: list[dict],
    covered_through: date | str | None,
) -> tuple[str, list[str]]:
    """Append-only edit. `bullets`: [{entry_id, section (phrasing|detail),
    text, date}] into EXISTING entries; `new_entries`: [{section (int),
    title, bullets: [{section, text, date}]}] become `### N.M Title `[WL]``
    blocks at the end of their period section. Then the watermark line is
    replaced (or appended). Returns (new text, ids of created entries).
    Raises ValueError on an unknown entry / a section outside 3-7."""
    rec = parse(text)
    lines = list(rec.lines)
    # (after_index, order, new_lines) — applied bottom-up so earlier indices
    # stay valid; `order` keeps same-point insertions in submission order.
    inserts: list[tuple[int, int, list[str]]] = []
    order = 0

    grouped: dict[tuple[str, str], list[dict]] = {}
    for b in bullets:
        if rec.entry(b["entry_id"]) is None:
            raise ValueError(f"no record entry {b['entry_id']!r}")
        if b.get("section") not in (PHRASING, DETAIL):
            raise ValueError(f"bad section {b.get('section')!r}")
        if not strip_tags(b.get("text", "")):
            continue
        grouped.setdefault((b["entry_id"], b["section"]), []).append(b)
    for (entry_id, section), items in grouped.items():
        entry = rec.entry(entry_id)
        after, needs_label = _insertion_point(lines, entry, section)
        block = [bullet_line(b["text"], b["date"]) for b in items]
        if needs_label:
            block = ["", f"**{SECTION_LABEL[section]}**", *block]
        inserts.append((after, order, block))
        order += 1

    created: list[str] = []
    next_seq: dict[int, int] = {}
    for ne in new_entries:
        num = int(ne["section"])
        if num not in ENTRY_SECTIONS or rec.section(num) is None:
            raise ValueError(f"new entries go in an existing period section 3-7, not {num}")
        title = strip_tags(ne.get("title", "")).strip()
        if not title:
            raise ValueError("a new entry needs a title")
        seq = next_seq.get(num) or int(next_entry_id(rec, num).split(".")[1])
        next_seq[num] = seq + 1
        entry_id = f"{num}.{seq}"
        created.append(entry_id)
        sec = rec.section(num)
        after = _last_content_line(lines, sec.start, sec.end)
        block = ["", f"### {entry_id} {title} `[WL]`"]
        for section in (DETAIL, PHRASING):
            items = [b for b in ne.get("bullets", []) if b.get("section") == section and strip_tags(b.get("text", ""))]
            if items:
                block += ["", f"**{SECTION_LABEL[section]}**", *[bullet_line(b["text"], b["date"]) for b in items]]
        inserts.append((after, order, block))
        order += 1

    for after, _, block in sorted(inserts, key=lambda t: (t[0], t[1]), reverse=True):
        lines[after + 1 : after + 1] = block
    out = "\n".join(lines)

    if covered_through is not None:
        marker = watermark_line(covered_through)
        if WATERMARK_RE.search(out):
            out = WATERMARK_RE.sub(marker, out)
        else:
            out = out.rstrip("\n") + "\n\n" + marker + "\n"
    return out, created


def org_names(rec: ParsedRecord) -> set[str]:
    """Employer / institution names the record itself states — from period
    headings ("Jan 2026 – present · Minfy Technologies, AI Engineer, ...")
    and `Work — X, Role` entry titles. Feeds the fact validator: a bullet
    naming one of these must have it in its sources."""
    names: set[str] = set()
    for s in rec.sections:
        if "·" in s.title:
            first = s.title.split("·", 1)[1].split(",")[0].strip()
            if first and first[0].isupper():
                names.add(first)
    for e in rec.entries:
        if e.title.lower().startswith("work"):
            rest = re.split(r"\s+[—-]\s+", e.title, maxsplit=1)
            if len(rest) == 2:
                first = rest[1].split(",")[0].split("(")[0].strip()
                if first:
                    names.add(first)
    return names
