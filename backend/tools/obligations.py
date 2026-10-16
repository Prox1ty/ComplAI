"""Extract and cache the obligations stated in a regulatory document.

Extraction runs once per document (keyed by ``content_hash``) and is stored in
the SQLite ``docs.obligations_json`` column, so every later run and every user
reuses it at zero token cost.
"""
from __future__ import annotations

import json
import logging

from pydantic import BaseModel, Field

from backend import llm
from backend.agents import prompts
from backend.agents.base import dumps
from backend.schemas import Obligation
from backend.taxonomy import keyword_topics, normalize_topics
from backend.tools import vectorstore as vs
from backend.tools.chunk import estimate_tokens
from backend.tools.quote import clip_words, quote_in_text
from backend.tools.registry import get_registry

log = logging.getLogger(__name__)
BATCH_TOKENS = 2600
MAX_TOKENS = 1500


class _Item(BaseModel):
    chunk_id: str
    text: str
    quote: str = ""
    topic: str = "other"
    modality: str = "must"


class _Out(BaseModel):
    obligations: list[_Item] = Field(default_factory=list)


def load_obligations(doc_id: str) -> list[Obligation] | None:
    meta = get_registry().get_doc(doc_id)
    if not meta or not meta.obligations_json:
        return None
    try:
        return [Obligation(**o) for o in json.loads(meta.obligations_json)]
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


async def obligation_extractor(doc_id: str) -> list[Obligation]:
    reg = get_registry()
    cached = load_obligations(doc_id)
    if cached is not None:
        return cached
    meta = reg.get_doc(doc_id)
    if meta is None:
        return []
    # identical content already extracted under another doc id
    if meta.content_hash:
        twin = reg.find_by_hash(meta.content_hash)
        if twin and twin.doc_id != doc_id and twin.obligations_json:
            reg.set_obligations(doc_id, twin.obligations_json)
            return load_obligations(doc_id) or []

    ids, docs, metas, _ = vs.get_store().get(vs.FACTS, where={"doc_id": doc_id})
    chunks = sorted(zip(ids, docs, [vs.decode_meta(m) for m in metas]), key=lambda x: x[0])
    batches: list[list[tuple[str, str, dict]]] = []
    cur: list[tuple[str, str, dict]] = []
    cur_tokens = 0
    cur_section = None
    for ch in chunks:
        t = estimate_tokens(ch[1])
        section = ch[2].get("section")
        if cur and (cur_tokens + t > BATCH_TOKENS or (section != cur_section and cur_tokens > BATCH_TOKENS // 2)):
            batches.append(cur)
            cur, cur_tokens = [], 0
        cur.append(ch)
        cur_tokens += t
        cur_section = section
    if cur:
        batches.append(cur)

    by_id = {c[0]: c[1] for c in chunks}
    out: list[Obligation] = []
    failed = False
    for batch in batches:
        user = dumps({"doc": meta.title, "CHUNKS": [{"chunk_id": cid, "text": text} for cid, text, _ in batch]})
        try:
            res = await llm.call("small", prompts.OBLIGATIONS, user, MAX_TOKENS, _Out, label="obligations")
        except llm.LLMError as e:
            log.warning("obligation extraction failed for %s: %s", doc_id, e)
            failed = True
            continue
        for item in res.obligations:
            src = by_id.get(item.chunk_id)
            if src is None:
                continue
            quote = clip_words(item.quote or "", 25)
            if not quote or not quote_in_text(quote, src):
                quote = ""
            topic = (normalize_topics([item.topic]) or keyword_topics(item.text, 1) or ["other"])[0]
            out.append(Obligation(
                id=f"{doc_id}-o{len(out) + 1}", text=item.text.strip(), topic=topic,
                modality=item.modality, chunk_id=item.chunk_id, quote=quote, doc_id=doc_id,
            ))
    if not failed:  # only cache complete extractions
        reg.set_obligations(doc_id, json.dumps([o.model_dump() for o in out]))
    return out
