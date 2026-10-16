"""Locate a short quote inside a longer text: exact, then normalised, then fuzzy.

Normalisation lower-cases, unifies quotes and dashes, and collapses
whitespace while keeping a map back to original offsets, so a normalised or
fuzzy match still returns positions in the original text.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

try:
    from rapidfuzz import fuzz  # type: ignore
except ImportError:  # pragma: no cover - exercised only without rapidfuzz
    fuzz = None

_TRANS = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"', "«": '"', "»": '"',
    "–": "-", "—": "-", "‒": "-", "−": "-", " ": " ",
})
NOT_FOUND = (-1, -1, 0.0)


def normalize(s: str) -> str:
    return _normalize_with_map(s)[0]


def _normalize_with_map(s: str) -> tuple[str, list[int]]:
    out: list[str] = []
    idx: list[int] = []
    prev_space = True
    for i, ch in enumerate(s):
        c = ch.translate(_TRANS).lower()
        if c.isspace():
            if prev_space:
                continue
            c = " "
            prev_space = True
        else:
            prev_space = False
        out.append(c)
        idx.append(i)
    while out and out[-1] == " ":
        out.pop()
        idx.pop()
    return "".join(out), idx


def _strip_ends(q: str) -> str:
    return q.strip().strip("\"'“”‘’").strip().rstrip(".…").strip()


def _partial(needle: str, hay: str) -> tuple[float, int, int]:
    """Best partial alignment of ``needle`` in ``hay`` -> (score 0-100, start, end) in hay."""
    if fuzz is not None:
        res = fuzz.partial_ratio_alignment(needle, hay)
        if res is None:
            return 0.0, -1, -1
        return float(res.score), res.dest_start, res.dest_end
    # difflib fallback: slide a window of len(needle) over word boundaries.
    n = len(needle)
    if n == 0 or not hay:
        return 0.0, -1, -1
    best = (0.0, -1, -1)
    starts = [0] + [m.end() for m in re.finditer(r"\s", hay)]
    for st in starts:
        window = hay[st:st + n]
        r = SequenceMatcher(None, needle, window, autojunk=False).ratio() * 100
        if r > best[0]:
            best = (r, st, min(len(hay), st + n))
    return best


def quote_matcher(quote: str, text: str, threshold: float = 85.0) -> tuple[int, int, float]:
    """Return ``(start, end, score)`` of ``quote`` in ``text``; ``(-1, -1, score)`` if below threshold."""
    q = _strip_ends(quote)
    if not q or not text:
        return NOT_FOUND
    pos = text.find(q)
    if pos >= 0:
        return pos, pos + len(q), 100.0
    nq = normalize(q)
    nt, idx = _normalize_with_map(text)
    if not nq or not nt:
        return NOT_FOUND
    pos = nt.find(nq)
    if pos >= 0:
        return idx[pos], idx[pos + len(nq) - 1] + 1, 99.0
    score, s, e = _partial(nq, nt)
    if s < 0 or score < threshold:
        return -1, -1, score
    # expand to word boundaries in the normalised text
    while s > 0 and nt[s - 1] != " ":
        s -= 1
    while e < len(nt) and nt[e - 1] != " " and nt[e] != " ":
        e += 1
    e = min(e, len(nt))
    while e > s and nt[e - 1] == " ":
        e -= 1
    return idx[s], idx[e - 1] + 1, score


def quote_in_text(quote: str, text: str, threshold: float = 90.0) -> bool:
    """Deterministic citation check used by the Verifier."""
    q = normalize(_strip_ends(quote))
    t = normalize(text)
    if not q:
        return False
    if q in t:
        return True
    return _partial(q, t)[0] >= threshold


def word_count(s: str) -> int:
    return len(s.split())


def clip_words(s: str, n: int = 25) -> str:
    words = s.split()
    return s if len(words) <= n else " ".join(words[:n])
