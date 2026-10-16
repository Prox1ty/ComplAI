"""RegulatorySearch: registry first, web only when coverage is thin.

Deterministic flow with a single small-model call (query generation).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from pydantic import BaseModel, Field

from backend import llm
from backend.agents import prompts
from backend.agents.base import RunContext, dumps
from backend.schemas import DocMeta, SearchHit
from backend.taxonomy import keyword_topics
from backend.tools import vectorstore as vs
from backend.tools.chunk import chunk_text
from backend.tools.embed import aembed
from backend.tools.fetch import fetch_and_extract
from backend.tools.obligations import load_obligations, obligation_extractor
from backend.tools.registry import content_hash, doc_id_for_url, get_registry
from backend.tools.sources import LOCAL_LANGUAGE, REGULATORS, issuer_for_url, jurisdiction_for_url, rank_results
from backend.tools.websearch import web_search
from backend.tools.geo import country_name

log = logging.getLogger(__name__)
MIN_DOCS_PER_TOPIC = 2
MAX_QUERIES = 6
FETCH_TOP = 5
FETCH_CONCURRENCY = 3


class QueryOut(BaseModel):
    queries: list[str] = Field(default_factory=list)


async def ingest_document(
    meta: DocMeta, text: str, pages: list[dict] | None = None, extract: bool = True
) -> int:
    """Chunk, embed and index a regulatory document, register it, and extract obligations."""
    meta.content_hash = meta.content_hash or content_hash(text)
    chunks = chunk_text(text, {
        "doc_id": meta.doc_id, "jurisdiction": meta.jurisdiction, "topics": meta.topics, "url": meta.url,
        "effective_date": meta.effective_date, "title": meta.title, "pages": pages,
    })
    if not chunks:
        return 0
    embs = await aembed([c.text for c in chunks], "passage")
    vs.vector_upsert(vs.FACTS, chunks, embs)
    get_registry().add_doc(meta)
    if extract:
        await obligation_extractor(meta.doc_id)
    return len(chunks)


def _fallback_queries(ctx: RunContext) -> list[str]:
    cname = country_name(ctx.inputs.country)
    regs = REGULATORS.get(ctx.inputs.country.upper(), [])
    year = ctx.as_of[:4]
    topic_words = [t.replace("_", " ") for t in ctx.profile.topics[:3]] or [ctx.inputs.policy_type]
    qs = [f"{cname} {regs[0] if regs else 'central bank'} {ctx.inputs.policy_type} regulations {year}"]
    for t in topic_words:
        qs.append(f"{cname} bank {t} regulation {regs[0] if regs else ''}".strip())
    if ctx.inputs.region:
        qs.append(f"{ctx.inputs.region} {cname} {ctx.inputs.policy_type} bank regulation")
    return qs[:MAX_QUERIES]


async def _queries(ctx: RunContext, missing_topics: list[str]) -> list[str]:
    user = dumps({
        "country": country_name(ctx.inputs.country), "country_code": ctx.inputs.country, "region": ctx.inputs.region,
        "city": ctx.inputs.city, "regulators": REGULATORS.get(ctx.inputs.country.upper(), []),
        "local_language": LOCAL_LANGUAGE.get(ctx.inputs.country.upper()), "policy_type": ctx.inputs.policy_type,
        "institution_type": ctx.inputs.institution_type, "topics": missing_topics, "as_of_year": ctx.as_of[:4],
    })
    try:
        out = await llm.call("small", prompts.QUERYGEN, user, 400, QueryOut, label="querygen")
        qs = [q.strip() for q in out.queries if q.strip()][:MAX_QUERIES]
        return qs or _fallback_queries(ctx)
    except llm.LLMError as e:
        ctx.log("errors", step="querygen", error=str(e))
        return _fallback_queries(ctx)


async def run(ctx: RunContext) -> list[DocMeta]:
    reg = get_registry()
    topics = ctx.profile.topics
    await ctx.emit("searching", "started", "Checking the regulation registry", 0.12)
    coverage = reg.topic_coverage(ctx.chain, topics)
    missing = [t for t, n in coverage.items() if n < MIN_DOCS_PER_TOPIC]

    if missing and ctx.inputs is not None:
        await ctx.emit("searching", "progress", f"Searching the web for {len(missing)} under-covered topic(s)", 0.15)
        queries = await _queries(ctx, missing)
        results = await asyncio.gather(*(web_search(q, k=6, country=ctx.inputs.country) for q in queries), return_exceptions=True)
        hits: dict[str, SearchHit] = {}
        for r in results:
            if isinstance(r, BaseException):
                ctx.log("errors", step="web_search", error=str(r))
                continue
            for h in r:
                hits.setdefault(doc_id_for_url(h.url), h)
        ranked = rank_results(list(hits.values()), min_score=0.5)
        fresh = [h for h in ranked if reg.get_doc(doc_id_for_url(h.url)) is None][:FETCH_TOP]
        await ctx.emit("searching", "progress", f"Reading {len(fresh)} official source(s)", 0.2)
        await _fetch_and_index(ctx, fresh, missing)
    else:
        await ctx.emit("searching", "progress", "Registry covers every topic; skipping web search", 0.2)

    docs = reg.get_docs(ctx.chain, topics) or reg.get_docs(ctx.chain)
    # make sure every discovered document has obligations (cached forever)
    pending = [d for d in docs if load_obligations(d.doc_id) is None]
    for i, d in enumerate(pending, start=1):
        await ctx.emit("searching", "progress", f"Extracting obligations ({i} of {len(pending)})", 0.22 + 0.06 * i / len(pending))
        await obligation_extractor(d.doc_id)
    ctx.docs = [reg.get_doc(d.doc_id) or d for d in docs]
    return ctx.docs


async def _fetch_and_index(ctx: RunContext, hits: list[SearchHit], missing_topics: list[str]) -> None:
    reg = get_registry()
    sem = asyncio.Semaphore(FETCH_CONCURRENCY)
    country_key = ctx.chain[-2] if len(ctx.chain) >= 2 else "global"
    country_key = next((k for k in ctx.chain if "/" not in k and k not in {"global", "EU", "EEA", "GCC"}), country_key)

    async def one(h: SearchHit):
        async with sem:
            try:
                return h, await fetch_and_extract(h.url)
            except Exception as e:  # noqa: BLE001
                ctx.log("skipped", url=h.url, reason=str(e)[:200])
                return h, None

    for h, doc in await asyncio.gather(*(one(h) for h in hits)):
        if doc is None:
            continue
        if reg.find_by_hash(doc.content_hash):
            continue
        detected = keyword_topics(doc.text[:20000], limit=6)
        topics = [t for t in detected if t in ctx.profile.topics] or [t for t in missing_topics if t in detected] or missing_topics[:3]
        meta = DocMeta(
            doc_id=doc_id_for_url(h.url), title=doc.title or h.title, issuer=issuer_for_url(h.url), url=h.url,
            jurisdiction=jurisdiction_for_url(h.url, country_key), topics=topics,
            effective_date=doc.published_date, fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            content_hash=doc.content_hash,
        )
        try:
            n = await ingest_document(meta, doc.text, [p.model_dump() for p in doc.pages], extract=False)
            await ctx.emit("searching", "progress", f"Indexed {meta.title[:60]} ({n} chunks)", 0.21)
        except Exception as e:  # noqa: BLE001
            ctx.log("errors", step="index", url=h.url, error=str(e)[:200])
