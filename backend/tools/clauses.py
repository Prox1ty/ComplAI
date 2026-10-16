"""Split a policy document into clauses with stable character offsets.

Strategy (in order):
1. Numbered lines (``1.``, ``1.1``, ``(a)``, ``a)``, ``(iv)``, ``Article 5``,
   ``Section 3.2``) start a new clause, unless the line is itself a short
   heading such as ``3. Customer Due Diligence``.
2. Heading lines (short, no terminal punctuation, title or upper case) set the
   current ``section`` and are not clauses.
3. If the document has no numbering at all, fall back to sentence splitting.
4. Fragments under ``MIN_WORDS`` words are merged into the previous clause.

All offsets refer to the exact text passed in, so ``text[c.start:c.end] ==
c.text`` always holds.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from backend.schemas import Clause

MIN_WORDS = 15
HEADING_MAX_WORDS = 10

NUM_RE = re.compile(
    r"""^[ \t]*(?P<label>
        (?:Article|Section|Clause|Rule|Regulation|Part|Chapter)\s+\d+[A-Za-z]?(?:\.\d+)*[.:]?
      | \d+(?:\.\d+)*\.?
      | \((?:[a-z]{1,2}|[ivxlc]{1,6}|\d{1,3})\)
      | (?:[a-z]|[ivxlc]{1,6})\)
    )[ \t]+(?=\S)""",
    re.VERBOSE,
)
SENT_RE = re.compile(r"(?<=[.!?;])\s+(?=[\"'(\[]?[A-Z0-9])")
WORD_RE = re.compile(r"\w+", re.UNICODE)


@dataclass
class _Line:
    start: int
    end: int  # exclusive, excludes the newline
    text: str


def _lines(text: str) -> list[_Line]:
    out: list[_Line] = []
    pos = 0
    for raw in text.split("\n"):
        out.append(_Line(pos, pos + len(raw), raw))
        pos += len(raw) + 1
    return out


def word_count(s: str) -> int:
    return len(WORD_RE.findall(s))


def is_heading(line: str) -> bool:
    """Heuristic heading detector, shared with the chunker."""
    s = line.strip()
    if not s:
        return False
    m = NUM_RE.match(s)
    body = s[m.end():] if m else s
    body = body.strip()
    if not body or word_count(body) > HEADING_MAX_WORDS:
        return False
    if body[-1] in ".;,!?":
        return False
    if body.startswith('"') or body.startswith("“"):
        return False
    letters = [ch for ch in body if ch.isalpha()]
    if not letters:
        return False
    if body.isupper():
        return True
    if re.match(r"^(Article|Section|Part|Chapter|Schedule|Annex|Appendix)\b", s, re.I) and word_count(body) <= 8:
        return True
    words = [w for w in re.split(r"\s+", body) if w]
    small = {"and", "or", "of", "the", "to", "for", "in", "on", "a", "an", "with", "by", "at"}
    caps = sum(1 for w in words if w[0].isupper() or not w[0].isalpha() or w.lower() in small)
    return caps == len(words) and word_count(body) <= 8


def heading_level(line: str) -> int:
    s = line.strip()
    m = NUM_RE.match(s)
    if m:
        label = m.group("label")
        if re.match(r"^(Part|Chapter)", label, re.I):
            return 1
        if re.match(r"^(Article|Section)", label, re.I):
            return 2
        return 1 + label.rstrip(".").count(".")
    return 1


def _trim(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def _sentence_clauses(text: str) -> list[tuple[int, int, str | None]]:
    spans: list[tuple[int, int, str | None]] = []
    section: str | None = None
    for para in re.finditer(r"[^\n]+(?:\n(?!\s*\n)[^\n]+)*", text):
        ps, pe = para.start(), para.end()
        chunk = text[ps:pe]
        if is_heading(chunk) and "\n" not in chunk.strip():
            section = chunk.strip()
            continue
        cursor = ps
        for m in SENT_RE.finditer(chunk):
            s, e = _trim(text, cursor, ps + m.start())
            if e > s:
                spans.append((s, e, section))
            cursor = ps + m.end()
        s, e = _trim(text, cursor, pe)
        if e > s:
            spans.append((s, e, section))
    return spans


def split_clauses(text: str) -> list[Clause]:
    lines = _lines(text)
    has_numbering = any(NUM_RE.match(ln.text) and not is_heading(ln.text) for ln in lines)

    raw: list[tuple[int, int, str | None, str | None]] = []  # start, end, section, label
    if has_numbering:
        section: str | None = None
        cur_start: int | None = None
        cur_end = 0
        cur_label: str | None = None
        cur_section: str | None = None

        def flush() -> None:
            nonlocal cur_start
            if cur_start is not None:
                s, e = _trim(text, cur_start, cur_end)
                if e > s:
                    raw.append((s, e, cur_section, cur_label))
            cur_start = None

        for ln in lines:
            stripped = ln.text.strip()
            if not stripped:
                continue
            if is_heading(ln.text):
                flush()
                section = stripped
                continue
            m = NUM_RE.match(ln.text)
            if m:
                flush()
                cur_start = ln.start
                cur_end = ln.end
                cur_label = m.group("label").strip().rstrip(".:")
                cur_section = section
            elif cur_start is not None:
                cur_end = ln.end
            else:
                cur_start, cur_end, cur_label, cur_section = ln.start, ln.end, None, section
        flush()
    else:
        raw = [(s, e, sec, None) for s, e, sec in _sentence_clauses(text)]

    # Merge short fragments into the previous clause (same section only, so a
    # short clause never swallows across a heading).
    merged: list[list] = []
    for s, e, sec, label in raw:
        frag = text[s:e]
        if merged and word_count(frag) < MIN_WORDS and merged[-1][2] == sec and not label:
            merged[-1][1] = e
        else:
            merged.append([s, e, sec, label])

    clauses: list[Clause] = []
    for i, (s, e, sec, label) in enumerate(merged, start=1):
        clauses.append(Clause(id=f"c{i}", text=text[s:e], start=s, end=e, section=sec, label=label))
    return clauses
