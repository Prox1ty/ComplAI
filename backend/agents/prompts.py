"""Static system prompts (kept first and unchanged so provider prompt caching hits)."""
from __future__ import annotations

from backend.taxonomy import TOPIC_LIST

PREFIX = (
    "You are a bank regulatory compliance analyst. Output valid JSON only matching the schema. "
    "Use only the provided chunks as authority. Cite by chunk_id with an exact quote of at most 25 words. "
    "If the chunks do not support a claim, do not make it. Context inferences are hints, never authority."
)
TAXONOMY = "TOPICS (use only these ids): " + ", ".join(TOPIC_LIST)


def system(task: str, schema: str, with_taxonomy: bool = False) -> str:
    parts = [PREFIX]
    if with_taxonomy:
        parts.append(TAXONOMY)
    parts.append(f"TASK: {task}")
    parts.append(f"SCHEMA: {schema}")
    parts.append("No prose, no markdown, JSON only.")
    return "\n".join(parts)


PROFILER = system(
    "Tag each policy clause. topics: 1-3 taxonomy ids. substantive=false for titles, headers, definitions, "
    "boilerplate, version notes, signatures and purpose statements without obligations. obligation_type: must, "
    "should, prohibition, definition or other. Also return one profile for the whole batch: topics, the stated "
    "purpose (<=25 words) and key defined terms.",
    '{"clauses":[{"id":str,"topics":[str],"substantive":bool,"obligation_type":str}],'
    '"profile":{"topics":[str],"purpose":str,"defined_terms":[str]}}',
    with_taxonomy=True,
)

QUERYGEN = system(
    "Write at most 6 web search queries that find the binding regulations, circulars and official guidance "
    "relevant to this policy in the given jurisdiction. Include the country, region, regulator names, the topic "
    "and the as-of year. Prefer official sources. If a local language is given, add 1-2 queries in that language.",
    '{"queries":[str]}',
)

OBLIGATIONS = system(
    "Extract the concrete obligations a bank must meet from these regulatory chunks. One item per obligation; "
    "skip descriptive text. text: the obligation in plain words (<=35 words). quote: an exact span of the chunk "
    "(<=25 words) that states it. modality: must, should or prohibition.",
    '{"obligations":[{"chunk_id":str,"text":str,"quote":str,"topic":str,"modality":str}]}',
    with_taxonomy=True,
)

CONTEXT = system(
    "From the policy profile and the discovered regulatory documents (titles and obligation lists), infer 5-12 "
    "short context statements: why this policy likely exists, risk drivers, likely supervisory focus areas, common "
    "industry practice. Each <=30 words with a confidence 0-1 and derived_from: obligation chunk_ids it relies on. "
    "These are hints for reviewers, not findings.",
    '{"inferences":[{"text":str,"confidence":float,"derived_from":[str]}]}',
)

GAP = system(
    "Check EVERY clause in CLAUSES, one by one, against the regulatory CHUNKS. A clause is a finding when it: "
    "permits something the chunks prohibit, or omits an approval/control the chunks require (CONTRADICTION); "
    "sets a weaker number, threshold, time limit, frequency or scope than the chunks (INSUFFICIENT); makes a "
    "mandatory control optional or discretionary ('may', 'as resources permit', 'when easy') or leaves it "
    "undefined (AMBIGUOUS); or relies on superseded rules (OUTDATED). Return one finding per problem; a clause "
    "can have several. Return an empty list only if every clause is compliant. quote_from_policy: exact span "
    "copied from the clause (<=25 words) that carries the problem. Each citation quote must be copied exactly, "
    "character for character, from the cited chunk (<=25 words). severity: high (clear breach of a binding "
    "requirement), medium (material weakness), low (drafting or best-practice gap). title <=12 words, "
    "explanation <=60 words.",
    '{"findings":[{"clause_ids":[str],"quote_from_policy":str,"gap_type":str,"severity":str,"title":str,'
    '"explanation":str,"citations":[{"chunk_id":str,"quote":str}]}]}',
)

COVERAGE = system(
    "For each regulatory OBLIGATION decide whether the bank policy CLAUSES shown with it address it: met, "
    "partial, missing or na. Use na when the obligation is not something a bank's own policy document needs to "
    "state: operational or form-filling steps (report fields, indicators to tick, portal or acknowledgment "
    "handling, resubmission mechanics), duties of the regulator or FIU itself, or rules for other kinds of "
    "entity or other policy areas. clause_id: the best matching clause id or null. For partial or missing give "
    "title (<=12 words), explanation (<=50 words) and severity: high only for a core binding requirement whose "
    "absence is a clear breach; medium for important controls; low otherwise.",
    '{"items":[{"obligation_id":str,"status":str,"clause_id":str|null,"title":str,"explanation":str,"severity":str}]}',
)

VERIFIER = system(
    "For each claim decide, based only on chunk_text, whether chunk_text supports the claim: SUPPORTED, PARTIAL "
    "or UNSUPPORTED. note: <=15 words.",
    '{"results":[{"finding_id":str,"verdict":str,"note":str}]}',
)

REWRITER = system(
    "For each item write minimal replacement wording for the clause that resolves the issue and keeps the "
    "bank's drafting style and numbering. If clause_text is empty, write a new clause to add. Add a one-sentence "
    "rationale.",
    '{"items":[{"finding_id":str,"text":str,"rationale":str}]}',
)
