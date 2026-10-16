"""Verifier (small model) - the only LLM gatekeeper.

1. Deterministic citation checks (no tokens): chunk exists in
   ``regulatory_facts``, its jurisdiction is in the run's chain, and the quote
   appears in the chunk (normalised substring or fuzzy >= 90).
2. Entailment check, 10 claims per call: SUPPORTED / PARTIAL / UNSUPPORTED.
3. UNSUPPORTED is dropped; a high-severity finding gets one regeneration with
   different chunks. PARTIAL is kept with a badge.
4. Date sanity: a cited document effective after ``as_of`` is flagged.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from backend import llm
from backend.agents import gap, prompts
from backend.agents.base import RunContext, dumps
from backend.agents.gap import Draft
from backend.schemas import Verification
from backend.tools import vectorstore as vs
from backend.tools.quote import quote_in_text
from backend.tools.registry import get_registry

BATCH = 10
MAX_TOKENS = 800
CHUNK_CHAR_CAP = 1800


class _Res(BaseModel):
    finding_id: str
    verdict: str = "UNSUPPORTED"
    note: str = ""


class _Out(BaseModel):
    results: list[_Res] = Field(default_factory=list)


def deterministic_check(ctx: RunContext, d: Draft) -> tuple[bool, str]:
    """Keep only citations that pass; return (ok, reason)."""
    ids = [c.chunk_id for c in d.finding.citations]
    chunks = vs.get_by_ids(vs.FACTS, ids)
    kept, reasons = [], []
    for c in d.finding.citations:
        ch = chunks.get(c.chunk_id)
        if ch is None:
            reasons.append(f"{c.chunk_id}: not in regulatory_facts")
            continue
        if ch.metadata.get("jurisdiction") not in ctx.chain:
            reasons.append(f"{c.chunk_id}: jurisdiction {ch.metadata.get('jurisdiction')} outside chain")
            continue
        if not c.quote or not quote_in_text(c.quote, ch.text):
            reasons.append(f"{c.chunk_id}: quote not found in chunk")
            continue
        kept.append(c)
    d.finding.citations = kept
    return bool(kept), "; ".join(reasons)


def _date_flag(ctx: RunContext, d: Draft) -> str | None:
    reg = get_registry()
    for c in d.finding.citations:
        doc = reg.get_doc(c.doc_id)
        if doc and doc.effective_date and doc.effective_date[:10] > ctx.as_of:
            return f"Cited document is effective from {doc.effective_date[:10]}, after the as-of date."
    return None


async def _entail(ctx: RunContext, drafts: list[Draft]) -> dict[str, _Res]:
    if not drafts:
        return {}
    texts = vs.get_by_ids(vs.FACTS, [d.finding.citations[0].chunk_id for d in drafts])
    claims = []
    for i, d in enumerate(drafts):
        ch = texts.get(d.finding.citations[0].chunk_id)
        claims.append({
            "finding_id": str(i), "claim": f"{d.finding.title}. {d.finding.explanation}",
            "chunk_text": (ch.text if ch else "")[:CHUNK_CHAR_CAP],
        })
    out = await llm.call("small", prompts.VERIFIER, dumps({"CLAIMS": claims}), MAX_TOKENS, _Out, label="verifier")
    return {r.finding_id: r for r in out.results}


async def _verify_batch(ctx: RunContext, batch: list[Draft]) -> list[tuple[Draft, str, str]]:
    """Return (draft, verdict, note); verdict UNVERIFIED if the LLM is unavailable."""
    try:
        res = await _entail(ctx, batch)
    except llm.LLMError as e:
        ctx.log("errors", step="verifier", error=str(e))
        return [(d, "UNVERIFIED", "Entailment check unavailable; citation passed deterministic checks.") for d in batch]
    out = []
    for i, d in enumerate(batch):
        r = res.get(str(i))
        verdict = (r.verdict.upper().strip() if r else "UNVERIFIED")
        if verdict not in {"SUPPORTED", "PARTIAL", "UNSUPPORTED"}:
            verdict = "UNVERIFIED"
        out.append((d, verdict, (r.note if r else "")[:160]))
    return out


async def run(ctx: RunContext, drafts: list[Draft]) -> list[Draft]:
    await ctx.emit("verifying", "started", "Checking citations", 0.72)
    passed: list[Draft] = []
    retry: list[Draft] = []
    for d in drafts:
        ok, why = deterministic_check(ctx, d)
        if ok:
            passed.append(d)
        elif d.finding.severity == "high" and d.source == "clause":
            retry.append(d)
            ctx.log("dropped", stage="deterministic", title=d.finding.title, reason=why, retried=True)
        else:
            ctx.log("dropped", stage="deterministic", title=d.finding.title, reason=why)

    kept: list[Draft] = []
    batches = [passed[i:i + BATCH] for i in range(0, len(passed), BATCH)]
    for bi, batch in enumerate(batches, start=1):
        await ctx.emit("verifying", "progress", f"Entailment batch {bi} of {len(batches)}", 0.72 + 0.1 * bi / max(1, len(batches)))
        for d, verdict, note in await _verify_batch(ctx, batch):
            if verdict == "UNSUPPORTED":
                if d.finding.severity == "high" and d.source == "clause":
                    retry.append(d)
                ctx.log("dropped", stage="entailment", title=d.finding.title, note=note, retried=d in retry)
                continue
            _apply(ctx, d, verdict, note)
            kept.append(d)

    # one regeneration for important findings
    if retry and not ctx.reduced:
        await ctx.emit("verifying", "progress", f"Re-checking {len(retry)} high-severity finding(s)", 0.84)
        regenerated: list[Draft] = []
        for d in retry:
            try:
                nd = await gap.regenerate(ctx, d)
            except llm.LLMError as e:
                ctx.log("errors", step="regenerate", error=str(e))
                nd = None
            if nd and deterministic_check(ctx, nd)[0]:
                regenerated.append(nd)
        for d, verdict, note in await _verify_batch(ctx, regenerated):
            if verdict == "UNSUPPORTED":
                ctx.log("dropped", stage="regenerated", title=d.finding.title, note=note)
                continue
            _apply(ctx, d, verdict, note)
            kept.append(d)
    return kept


def _apply(ctx: RunContext, d: Draft, verdict: str, note: str) -> None:
    status = {"SUPPORTED": "verified", "PARTIAL": "partial"}.get(verdict, "unverified")
    flag = _date_flag(ctx, d)
    if flag:
        note = f"{note} {flag}".strip()
        if status == "verified":
            status = "partial"
    d.finding.verification = Verification(status=status, note=note or None)  # type: ignore[arg-type]
    if status == "unverified":
        ctx.log("unverified", title=d.finding.title, note=note)
