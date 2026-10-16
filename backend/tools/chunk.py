"""Section-aware chunking of regulatory text.

Chunks aim for 300-450 tokens (estimated at ~4 characters per token), with a
~50 token overlap inside a section. Each chunk is prefixed with its heading
path, which is also stored in metadata as ``section``.
"""
from __future__ import annotations

import math
import re
from typing import Any

from backend.schemas import Chunk
from backend.tools.clauses import heading_level, is_heading

TARGET_TOKENS = 380
MAX_TOKENS = 450
MIN_TOKENS = 300
OVERLAP_TOKENS = 50
SENT_RE = re.compile(r"(?<=[.!?;:])\s+")


def estimate_tokens(s: str) -> int:
    return max(1, math.ceil(len(s) / 4))


def _split_long(text: str, budget: int) -> list[str]:
    """Split a paragraph that exceeds the budget by sentences, then by words."""
    if estimate_tokens(text) <= budget:
        return [text]
    out: list[str] = []
    cur = ""
    for sent in SENT_RE.split(text):
        if estimate_tokens(sent) > budget:
            if cur:
                out.append(cur)
                cur = ""
            words = sent.split()
            piece: list[str] = []
            for w in words:
                if estimate_tokens(" ".join(piece + [w])) > budget and piece:
                    out.append(" ".join(piece))
                    piece = []
                piece.append(w)
            if piece:
                out.append(" ".join(piece))
            continue
        cand = f"{cur} {sent}".strip()
        if estimate_tokens(cand) > budget and cur:
            out.append(cur)
            cur = sent
        else:
            cur = cand
    if cur:
        out.append(cur)
    return out


def _tail(text: str, tokens: int) -> str:
    words = text.split()
    acc: list[str] = []
    for w in reversed(words):
        if estimate_tokens(" ".join([w] + acc)) > tokens:
            break
        acc.insert(0, w)
    return " ".join(acc)


def _page_for(offset: int, pages: list[dict] | None) -> int | None:
    if not pages:
        return None
    for p in pages:
        if p["start"] <= offset <= p["end"]:
            return p["number"]
    return pages[-1]["number"]


def chunk_text(text: str, doc_meta: dict[str, Any]) -> list[Chunk]:
    """Chunk ``text``. ``doc_meta`` must contain ``doc_id``; other keys
    (jurisdiction, topics, url, effective_date, pages) are copied into metadata."""
    doc_id = doc_meta["doc_id"]
    pages = doc_meta.get("pages")

    # 1. Sections: (heading_path, [(paragraph, offset)])
    sections: list[tuple[str, list[tuple[str, int]]]] = []
    stack: list[tuple[int, str]] = []
    cur_paras: list[tuple[str, int]] = []
    cur_path = ""
    for m in re.finditer(r"[^\n]+(?:\n(?!\s*\n)[^\n]+)*", text):
        block = m.group(0).strip()
        if not block:
            continue
        first_line = block.split("\n", 1)[0]
        if is_heading(first_line):
            if cur_paras:
                sections.append((cur_path, cur_paras))
                cur_paras = []
            lvl = heading_level(first_line)
            while stack and stack[-1][0] >= lvl:
                stack.pop()
            stack.append((lvl, first_line.strip()))
            cur_path = " > ".join(h for _, h in stack)
            rest = block.split("\n", 1)[1].strip() if "\n" in block else ""
            if rest:
                cur_paras.append((re.sub(r"\s+", " ", rest), m.start()))
            continue
        cur_paras.append((re.sub(r"\s+", " ", block), m.start()))
    if cur_paras:
        sections.append((cur_path, cur_paras))

    # 2. Pack paragraphs into chunks per section.
    chunks: list[Chunk] = []
    base_meta = {k: v for k, v in doc_meta.items() if k not in {"pages", "doc_id"}}
    for path, paras in sections:
        prefix = f"{path}\n" if path else ""
        budget = MAX_TOKENS - estimate_tokens(prefix)
        budget = max(budget, 120)
        pieces: list[tuple[str, int]] = []
        for p, off in paras:
            for part in _split_long(p, min(budget, TARGET_TOKENS)):
                pieces.append((part, off))
        body = ""
        body_off = pieces[0][1] if pieces else 0
        for part, off in pieces:
            cand = f"{body}\n{part}".strip() if body else part
            if body and estimate_tokens(cand) > budget:
                chunks.append(_mk(doc_id, len(chunks), prefix, body, path, body_off, pages, base_meta))
                overlap = _tail(body, OVERLAP_TOKENS)
                body = f"{overlap}\n{part}".strip() if overlap else part
                if estimate_tokens(body) > budget:
                    body = part
                body_off = off
            else:
                body = cand
        if body:
            chunks.append(_mk(doc_id, len(chunks), prefix, body, path, body_off, pages, base_meta))

    # 3. Fold very small chunks (tiny sections) into their predecessor so the
    #    store is not flooded with 20-token fragments.
    merged: list[Chunk] = []
    for c in chunks:
        if (
            merged
            and estimate_tokens(c.text) < MIN_TOKENS // 2
            and estimate_tokens(merged[-1].text) + estimate_tokens(c.text) <= MAX_TOKENS
        ):
            merged[-1].text = f"{merged[-1].text}\n{c.text}"
        else:
            merged.append(c)
    for i, c in enumerate(merged):
        cid = f"{doc_id}:{i:04d}"
        c.id = cid
        c.metadata["chunk_id"] = cid
    return merged


def _mk(doc_id: str, i: int, prefix: str, body: str, path: str, off: int, pages, base_meta) -> Chunk:
    meta = dict(base_meta)
    meta.update({"doc_id": doc_id, "chunk_id": f"{doc_id}:{i:04d}", "section": path or None})
    page = _page_for(off, pages)
    if page is not None:
        meta["page"] = page
    return Chunk(id=f"{doc_id}:{i:04d}", text=f"{prefix}{body}", metadata=meta)
