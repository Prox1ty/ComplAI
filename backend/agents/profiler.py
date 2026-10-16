"""PolicyProfiler (small model): tag clauses and build the policy profile."""
from __future__ import annotations

from pydantic import BaseModel, Field

from backend import llm
from backend.agents import prompts
from backend.agents.base import RunContext, dumps
from backend.schemas import ClauseTag, PolicyProfile
from backend.taxonomy import POLICY_TYPE_TOPICS, heuristic_tag, normalize_topics

BATCH = 40
MAX_TOKENS = 1500


class ProfilerOut(BaseModel):
    clauses: list[ClauseTag] = Field(default_factory=list)
    profile: PolicyProfile = Field(default_factory=PolicyProfile)


def _heuristic(cid: str, text: str) -> ClauseTag:
    topics, sub, ot = heuristic_tag(text)
    return ClauseTag(id=cid, topics=topics, substantive=sub, obligation_type=ot)  # type: ignore[arg-type]


async def run(ctx: RunContext) -> PolicyProfile:
    clauses = ctx.clauses
    tags: dict[str, ClauseTag] = {}
    profiles: list[PolicyProfile] = []
    batches = [clauses[i:i + BATCH] for i in range(0, len(clauses), BATCH)]
    for bi, batch in enumerate(batches, start=1):
        await ctx.emit("parsing", "progress", f"Profiling clauses (batch {bi} of {len(batches)})", 0.04 + 0.05 * bi / len(batches))
        user = dumps({
            "policy_type": ctx.inputs.policy_type,
            "CLAUSES": [{"id": c.id, "section": c.section, "text": c.text[:200]} for c in batch],
        })
        try:
            out = await llm.call("small", prompts.PROFILER, user, MAX_TOKENS, ProfilerOut, label="profiler")
            got = {t.id: t for t in out.clauses}
            profiles.append(out.profile)
        except llm.LLMError as e:
            ctx.log("errors", step="profiler", batch=bi, error=str(e))
            got = {}
        for c in batch:
            t = got.get(c.id)
            if t is None:
                t = _heuristic(c.id, c.text)
            t.topics = normalize_topics(t.topics) or normalize_topics(_heuristic(c.id, c.text).topics) or ["other"]
            if t.obligation_type == "definition":
                t.substantive = False
            tags[c.id] = t

    ctx.tags = tags
    defaults = POLICY_TYPE_TOPICS.get(ctx.inputs.policy_type, POLICY_TYPE_TOPICS["Other"])
    topic_counts: dict[str, int] = {}
    for t in tags.values():
        if t.substantive:
            for tp in t.topics:
                topic_counts[tp] = topic_counts.get(tp, 0) + 1
    llm_topics = normalize_topics([tp for p in profiles for tp in p.topics])
    topics: list[str] = []
    for tp in llm_topics + sorted(topic_counts, key=lambda k: -topic_counts[k]):
        if tp not in topics and tp != "other":
            topics.append(tp)
    if not topics:
        topics = list(defaults)
    terms: list[str] = []
    for p in profiles:
        for term in p.defined_terms:
            if term not in terms:
                terms.append(term)
    purpose = next((p.purpose for p in profiles if p.purpose), "")
    ctx.profile = PolicyProfile(topics=topics[:10], purpose=purpose, defined_terms=terms[:20])
    return ctx.profile
