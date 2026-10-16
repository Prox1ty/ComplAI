"""Rewriter (small model): drop-in replacement wording for each kept finding."""
from __future__ import annotations

from pydantic import BaseModel, Field

from backend import llm
from backend.agents import prompts
from backend.agents.base import RunContext, dumps
from backend.agents.gap import Draft
from backend.schemas import Suggestion

BATCH = 8
MAX_TOKENS = 1500


class _Item(BaseModel):
    finding_id: str
    text: str = ""
    rationale: str = ""


class _Out(BaseModel):
    items: list[_Item] = Field(default_factory=list)


async def run(ctx: RunContext, drafts: list[Draft]) -> None:
    batches = [drafts[i:i + BATCH] for i in range(0, len(drafts), BATCH)]
    for bi, batch in enumerate(batches, start=1):
        await ctx.emit("suggesting", "progress" if bi > 1 else "started", f"Drafting rewrites {bi} of {len(batches)}",
                       0.86 + 0.1 * bi / max(1, len(batches)))
        items = []
        for i, d in enumerate(batch):
            f = d.finding
            clause_text = " ".join(c.text for c in (ctx.clause(x) for x in f.clause_ids) if c)
            items.append({
                "finding_id": str(i), "clause_text": clause_text[:1500],
                "quote": f.citations[0].quote if f.citations else "",
                "issue": f"{f.title}. {f.explanation}",
                **({"section": d.section} if f.gap_type == "MISSING" and d.section else {}),
            })
        try:
            out = await llm.call("small", prompts.REWRITER, dumps({"ITEMS": items}), MAX_TOKENS, _Out, label="rewriter")
            got = {it.finding_id: it for it in out.items}
        except llm.LLMError as e:
            ctx.log("errors", step="rewriter", error=str(e))
            got = {}
        for i, d in enumerate(batch):
            it = got.get(str(i))
            d.finding.suggestion = (
                Suggestion(text=it.text.strip(), rationale=it.rationale.strip())
                if it and it.text.strip()
                else Suggestion(text="", rationale="Suggestion unavailable for this finding.")
            )
