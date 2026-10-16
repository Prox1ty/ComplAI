"""ContextAgent (large model): short inferences about why the policy exists and
where supervisors focus. Stored in ``context_inferences``; never authority."""
from __future__ import annotations

from pydantic import BaseModel, Field

from backend import llm
from backend.agents import prompts
from backend.agents.base import RunContext, dumps
from backend.schemas import Chunk, Inference
from backend.tools import vectorstore as vs
from backend.tools.embed import aembed
from backend.tools.geo import country_name
from backend.tools.obligations import load_obligations
from backend.tools.websearch import web_search

MAX_TOKENS = 1200
OBLIGATIONS_PER_DOC = 12


class _Inf(BaseModel):
    text: str
    confidence: float = 0.5
    derived_from: list[str] = Field(default_factory=list)


class _Out(BaseModel):
    inferences: list[_Inf] = Field(default_factory=list)


async def run(ctx: RunContext) -> list[Inference]:
    await ctx.emit("searching", "progress", "Building regulatory context", 0.3)
    docs_payload = []
    known_chunks: set[str] = set()
    for d in ctx.docs[:8]:
        obs = [o for o in (load_obligations(d.doc_id) or []) if o.topic in ctx.profile.topics or not ctx.profile.topics]
        obs = obs[:OBLIGATIONS_PER_DOC]
        known_chunks.update(o.chunk_id for o in obs)
        docs_payload.append({"title": d.title, "jurisdiction": d.jurisdiction,
                             "obligations": [{"chunk_id": o.chunk_id, "text": o.text} for o in obs]})

    news: list[dict] = []
    if not ctx.reduced:
        q = f"{country_name(ctx.inputs.country)} {ctx.inputs.policy_type} bank enforcement action supervisory guidance {ctx.as_of[:4]}"
        try:
            news = [{"title": h.title, "snippet": h.snippet[:200]} for h in (await web_search(q, k=5, country=ctx.inputs.country))]
        except Exception as e:  # noqa: BLE001
            ctx.log("errors", step="context_search", error=str(e)[:200])

    user = dumps({
        "jurisdiction": ctx.chain, "institution_type": ctx.inputs.institution_type, "policy_type": ctx.inputs.policy_type,
        "profile": ctx.profile.model_dump(), "DOCS": docs_payload, "RECENT": news,
    })
    try:
        out = await llm.call("large", prompts.CONTEXT, user, MAX_TOKENS, _Out, label="context")
    except llm.LLMError as e:
        ctx.log("errors", step="context", error=str(e))
        return []

    infs: list[Inference] = []
    for i, it in enumerate(out.inferences[:12], start=1):
        infs.append(Inference(
            id=f"{ctx.run_id}-i{i}", text=it.text.strip(), confidence=max(0.0, min(1.0, it.confidence)),
            derived_from=[c for c in it.derived_from if c in known_chunks],
        ))
    if infs:
        chunks = [
            Chunk(id=inf.id, text=inf.text, metadata={
                "run_id": ctx.run_id, "inf_id": inf.id, "confidence": inf.confidence, "derived_from": inf.derived_from,
            })
            for inf in infs
        ]
        vs.vector_upsert(vs.INFERENCES, chunks, await aembed([c.text for c in chunks], "passage"))
    ctx.inferences = infs
    return infs
