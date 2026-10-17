"""GapAnalysis (large model).

Pass A reviews substantive clauses in topic groups against retrieved
regulatory chunks. Pass B walks the stored obligations and checks whether the
policy covers each one, which is how omissions (MISSING) are found.
The LLM never produces offsets: spans are resolved in code.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from backend import llm
from backend.agents import prompts
from backend.agents.base import RunContext, dumps
from backend.config import settings
from backend.schemas import SEVERITY_RANK, Citation, Clause, Finding, Hit, Obligation, Span
from backend.tools import vectorstore as vs
from backend.tools.obligations import load_obligations
from backend.tools.quote import clip_words, quote_matcher
from backend.tools.registry import get_registry

MAX_TOKENS = 1500
COVERAGE_MAX_TOKENS = 1200
CHUNK_CHAR_CAP = 1800  # ~450 tokens
GROUP_MAX = 4
PER_CLAUSE_K = 3
COVERAGE_BATCH = 10
MAX_OBLIGATIONS = 60
MAX_MISSING = 5
GAP_TYPES = {"CONTRADICTION", "INSUFFICIENT", "AMBIGUOUS", "OUTDATED"}


# --------------------------------------------------------------------------
# LLM output schemas
# --------------------------------------------------------------------------
class _Cite(BaseModel):
    chunk_id: str
    quote: str = ""


class _Finding(BaseModel):
    clause_ids: list[str] = Field(default_factory=list)
    quote_from_policy: str = ""
    gap_type: str = "INSUFFICIENT"
    severity: str = "medium"
    title: str = ""
    explanation: str = ""
    citations: list[_Cite] = Field(default_factory=list)


class _GapOut(BaseModel):
    findings: list[_Finding] = Field(default_factory=list)


class _CovItem(BaseModel):
    obligation_id: str
    status: str = "partial"
    clause_id: str | None = None
    title: str = ""
    explanation: str = ""
    severity: str = "medium"


class _CovOut(BaseModel):
    items: list[_CovItem] = Field(default_factory=list)


@dataclass
class Draft:
    finding: Finding
    seen_chunks: set[str] = field(default_factory=set)
    query: str = ""
    topics: list[str] = field(default_factory=list)
    source: str = "clause"  # clause | coverage
    section: str | None = None


@dataclass
class CoverageResult:
    total: int = 0
    met: int = 0
    partial: int = 0
    missing: int = 0
    not_applicable: int = 0
    drafts: list[Draft] = field(default_factory=list)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def group_clauses(clauses: list[Clause], tags: dict) -> list[list[Clause]]:
    """Group by primary topic (document order kept), then into groups of 3-5."""
    by_topic: dict[str, list[Clause]] = {}
    for c in clauses:
        t = tags.get(c.id)
        topic = (t.topics[0] if t and t.topics else "other")
        by_topic.setdefault(topic, []).append(c)
    # fold singleton topics into a shared bucket so groups are not tiny
    groups: list[list[Clause]] = []
    leftovers: list[Clause] = []
    for topic, cs in by_topic.items():
        if len(cs) < 3:
            leftovers.extend(cs)
            continue
        n = -(-len(cs) // GROUP_MAX)
        size = -(-len(cs) // n)
        groups.extend(cs[i:i + size] for i in range(0, len(cs), size))
    leftovers.sort(key=lambda c: c.start)
    if leftovers:
        n = -(-len(leftovers) // GROUP_MAX)
        size = -(-len(leftovers) // n)
        groups.extend(leftovers[i:i + size] for i in range(0, len(leftovers), size))
    return groups


def _chunk_payload(h: Hit) -> dict:
    return {
        "chunk_id": h.id,
        "source": h.metadata.get("title") or h.metadata.get("doc_id"),
        "section": h.metadata.get("section"),
        "text": h.text[:CHUNK_CHAR_CAP],
    }


def make_citation(chunk_id: str, quote: str, known: dict[str, Hit]) -> Citation:
    h = known.get(chunk_id) or vs.get_by_ids(vs.FACTS, [chunk_id]).get(chunk_id)
    meta = h.metadata if h else {}
    doc_id = meta.get("doc_id") or chunk_id.split(":")[0]
    doc = get_registry().get_doc(doc_id)
    return Citation(
        doc_id=doc_id, chunk_id=chunk_id, quote=clip_words(quote.strip().strip('"“”'), 25),
        source_title=(doc.title if doc else meta.get("title")) or doc_id,
        source_url=(doc.url if doc else meta.get("url")) or "",
        section=meta.get("section"),
    )


def _norm_sev(s: str) -> str:
    s = (s or "").lower().strip()
    return s if s in SEVERITY_RANK else "medium"


def _norm_gap(g: str) -> str:
    g = (g or "").upper().strip()
    return g if g in GAP_TYPES else "INSUFFICIENT"


def _resolve_span(ctx: RunContext, clause_ids: list[str], quote: str) -> tuple[Span, list[str]]:
    clauses = [c for c in (ctx.clause(i) for i in clause_ids) if c]
    for c in clauses:
        s, e, _ = quote_matcher(quote, c.text)
        if s >= 0:
            return Span(start=c.start + s, end=c.start + e), [c.id]
    if clauses:
        return Span(start=clauses[0].start, end=clauses[0].end), [clauses[0].id]
    return Span(start=0, end=0), []


def _build_draft(ctx: RunContext, raw: _Finding, group: list[Clause], hits: dict[str, Hit], infs: list[Hit], query: str) -> Draft | None:
    group_ids = {c.id for c in group}
    cids = [c for c in raw.clause_ids if c in group_ids]
    if not cids:
        # locate the quote in the group instead
        cids = [c.id for c in group if quote_matcher(raw.quote_from_policy, c.text)[0] >= 0][:1]
    if not cids or not raw.citations:
        return None
    span, located = _resolve_span(ctx, cids, raw.quote_from_policy)
    cites = [make_citation(c.chunk_id, c.quote, hits) for c in raw.citations[:3] if c.chunk_id]
    if not cites:
        return None
    topics = sorted({t for c in cids for t in getattr(ctx.tags.get(c), "topics", [])})
    f = Finding(
        id="", clause_ids=cids, span=span, gap_type=_norm_gap(raw.gap_type), severity=_norm_sev(raw.severity),
        title=raw.title.strip()[:140] or "Potential compliance gap", explanation=raw.explanation.strip()[:800],
        citations=cites, inference_notes=[i.text for i in infs],
    )
    return Draft(finding=f, seen_chunks=set(hits), query=query, topics=topics)


def retrieve_for_group(ctx: RunContext, group: list[Clause], k: int, exclude: set[str] | None = None) -> list[Hit]:
    """Retrieve per clause, then merge round-robin so every clause gets its own best evidence.

    One query built from 3-5 concatenated clauses blurs into a generic AML
    vector and misses the specific rule each clause needs. Document-level topic
    tags are too coarse to filter on (they hid the main regulation from whole
    groups), so retrieval is filtered by jurisdiction only and ranked by the
    clause text itself.
    """
    per_clause = [
        vs.hybrid_search(vs.FACTS, c.text, {"jurisdiction": ctx.chain}, k=PER_CLAUSE_K, exclude_ids=exclude)
        for c in group
    ]
    hits: list[Hit] = []
    seen: set[str] = set()
    for rank in range(PER_CLAUSE_K):
        for lst in per_clause:
            if rank < len(lst) and lst[rank].id not in seen and len(hits) < k:
                seen.add(lst[rank].id)
                hits.append(lst[rank])
    return hits


async def _review_group(ctx: RunContext, group: list[Clause], k: int, exclude: set[str] | None = None) -> list[Draft]:
    query = " ".join(c.text for c in group)[:1500]
    hits = retrieve_for_group(ctx, group, k, exclude)
    if not hits:
        ctx.log("skipped", step="gap", clauses=[c.id for c in group], reason="no regulatory chunks retrieved")
        return []
    infs = vs.hybrid_search(vs.INFERENCES, query, {"run_id": ctx.run_id}, k=2)
    user = dumps({
        "jurisdiction": ctx.chain, "as_of": ctx.as_of,
        "CLAUSES": [{"id": c.id, "text": c.text} for c in group],
        "CHUNKS": [_chunk_payload(h) for h in hits],
        "INFERENCES": [{"id": h.id, "text": h.text} for h in infs],
    })
    try:
        out = await llm.call("large", prompts.GAP, user, MAX_TOKENS, _GapOut, label="gap")
    except llm.LLMError as e:
        ctx.log("errors", step="gap", clauses=[c.id for c in group], error=str(e))
        return []
    by_id = {h.id: h for h in hits}
    drafts = []
    for raw in out.findings:
        d = _build_draft(ctx, raw, group, by_id, infs, query)
        if d:
            drafts.append(d)
        else:
            ctx.log("dropped", stage="gap_build", title=raw.title, reason="no valid clause or citation")
    return drafts


# --------------------------------------------------------------------------
# Pass A
# --------------------------------------------------------------------------
async def pass_a(ctx: RunContext) -> list[Draft]:
    groups = group_clauses(ctx.substantive, ctx.tags)
    done = 0
    out: list[Draft] = []

    async def one(g: list[Clause]) -> list[Draft]:
        nonlocal done
        res = await _review_group(ctx, g, k=4 if ctx.reduced else 6)
        done += 1
        await ctx.emit("analysing", "progress", f"Reviewing group {done} of {len(groups)}", 0.4 + 0.2 * done / max(1, len(groups)))
        return res

    await ctx.emit("analysing", "started", f"Reviewing group 1 of {len(groups)}", 0.4)
    for res in await asyncio.gather(*(one(g) for g in groups)):
        out.extend(res)
    return out


async def regenerate(ctx: RunContext, draft: Draft) -> Draft | None:
    """One retry for an important finding using different chunks."""
    if draft.source != "clause":
        return None
    group = [c for c in (ctx.clause(i) for i in draft.finding.clause_ids) if c]
    if not group:
        return None
    res = await _review_group(ctx, group, k=4, exclude=draft.seen_chunks)
    if not res:
        return None
    best = max(res, key=lambda d: SEVERITY_RANK[d.finding.severity])
    best.seen_chunks |= draft.seen_chunks
    return best


# --------------------------------------------------------------------------
# Pass B
# --------------------------------------------------------------------------
def _section_end(ctx: RunContext, clause_id: str | None) -> tuple[int, str | None]:
    c = ctx.clause(clause_id) if clause_id else None
    if c is None:
        last = ctx.clauses[-1] if ctx.clauses else None
        return (last.end if last else 0), (last.section if last else None)
    same = [x for x in ctx.clauses if x.section == c.section]
    return max(x.end for x in same), c.section


def select_obligations(ctx: RunContext, topics: set[str]) -> list[Obligation]:
    """Pick the obligations to check, fairly across documents.

    Taking them in document order let one long procedural guideline fill the
    whole budget. Instead: binding (must/prohibition) obligations first, then
    round-robin across documents so each regulation is represented.
    """
    cap = MAX_OBLIGATIONS // 2 if ctx.reduced else MAX_OBLIGATIONS
    per_doc: list[list[Obligation]] = []
    seen_text: set[str] = set()
    for d in ctx.docs:
        items = []
        for o in load_obligations(d.doc_id) or []:
            key = " ".join(o.text.lower().split())
            if (not topics or o.topic in topics) and key not in seen_text:
                seen_text.add(key)
                items.append(o)
        items.sort(key=lambda o: 0 if o.modality in ("must", "prohibition") else 1)  # stable: keeps doc order
        if items:
            per_doc.append(items)
    out: list[Obligation] = []
    i = 0
    while len(out) < cap and any(i < len(lst) for lst in per_doc):
        for lst in per_doc:
            if i < len(lst) and len(out) < cap:
                out.append(lst[i])
        i += 1
    return out


async def pass_b(ctx: RunContext) -> CoverageResult:
    topics = set(ctx.profile.topics)
    obligations = select_obligations(ctx, topics)
    res = CoverageResult(total=len(obligations))
    if not obligations:
        return res

    await ctx.emit("analysing", "progress", f"Coverage check: {len(obligations)} obligations", 0.62)
    matches: dict[str, list[Hit]] = {}
    middle: list[Obligation] = []
    candidates: list[Obligation] = []
    for o in obligations:
        hits = vs.hybrid_search(vs.CLAUSES, o.text, {"run_id": ctx.run_id, "substantive": True}, k=3)
        matches[o.id] = hits
        best = max((h.dense for h in hits), default=0.0)
        if best >= settings.coverage_high:
            res.met += 1
        elif best < settings.coverage_low:
            candidates.append(o)
        else:
            middle.append(o)

    to_check = candidates + ([] if ctx.reduced else middle)
    if ctx.reduced:
        res.partial += len(middle)
    obl_by_id = {o.id: o for o in obligations}
    batches = [to_check[i:i + COVERAGE_BATCH] for i in range(0, len(to_check), COVERAGE_BATCH)]
    missing_items: list[tuple[_CovItem, Obligation]] = []

    progress = {"done": 0}

    async def one(batch: list[Obligation]) -> None:
        await _check(batch)
        progress["done"] += 1
        await ctx.emit("analysing", "progress", f"Coverage batch {progress['done']} of {len(batches)}",
                       0.62 + 0.08 * progress["done"] / len(batches))

    async def _check(batch: list[Obligation]) -> None:
        user = dumps({
            "jurisdiction": ctx.chain,
            "OBLIGATIONS": [
                {"obligation_id": o.id, "text": o.text,
                 "CLAUSES": [{"id": h.metadata.get("clause_id", h.id), "text": h.text[:500]} for h in matches[o.id]]}
                for o in batch
            ],
        })
        try:
            out = await llm.call("large", prompts.COVERAGE, user, COVERAGE_MAX_TOKENS, _CovOut, label="coverage")
        except llm.LLMError as e:
            ctx.log("errors", step="coverage", error=str(e))
            res.partial += len(batch)
            return
        answered = set()
        for it in out.items:
            o = obl_by_id.get(it.obligation_id)
            if o is None or o.id in answered or o not in batch:
                continue
            answered.add(o.id)
            st = it.status.lower().strip().replace("/", "").replace("_", "").replace(" ", "")
            if st in ("na", "notapplicable"):
                res.total -= 1  # procedural or not a bank-policy obligation: out of scope
                res.not_applicable += 1
            elif st == "met":
                res.met += 1
            elif st == "missing":
                res.missing += 1
                missing_items.append((it, o))
            else:
                res.partial += 1
        res.partial += len([o for o in batch if o.id not in answered])

    await asyncio.gather(*(one(b) for b in batches))

    # Build MISSING findings (citation = the obligation's own chunk)
    missing_items.sort(key=lambda x: -SEVERITY_RANK[_norm_sev(x[0].severity)])
    for it, o in missing_items[:MAX_MISSING]:
        chunk = vs.get_by_ids(vs.FACTS, [o.chunk_id]).get(o.chunk_id)
        if chunk is None:
            ctx.log("dropped", stage="coverage", obligation=o.id, reason="obligation chunk not found")
            continue
        quote = o.quote or clip_words(chunk.text.split("\n", 1)[-1], 25)
        related = it.clause_id if it.clause_id and ctx.clause(it.clause_id) else (
            matches[o.id][0].metadata.get("clause_id") if matches.get(o.id) else None)
        anchor, section = _section_end(ctx, related)
        f = Finding(
            id="", clause_ids=[], span=Span(start=anchor, end=anchor), gap_type="MISSING",
            severity=_norm_sev(it.severity), title=(it.title or f"Missing: {o.text[:60]}").strip()[:140],
            explanation=(it.explanation or f"The policy does not address this obligation: {o.text}").strip()[:800],
            citations=[make_citation(o.chunk_id, quote, {chunk.id: chunk})],
        )
        d = Draft(finding=f, seen_chunks={o.chunk_id}, query=o.text, topics=[o.topic], source="coverage")
        d.section = section
        res.drafts.append(d)
    return res
