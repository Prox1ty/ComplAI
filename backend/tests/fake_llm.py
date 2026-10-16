"""Deterministic stand-in for the LLM provider, keyed on the static system prompt.

It produces schema-valid, plausible outputs from the JSON user payload so the
whole pipeline can run offline in tests.
"""
from __future__ import annotations

import json
import re

from backend.agents import prompts
from backend.llm import Completion
from backend.taxonomy import heuristic_tag, keyword_topics


def _body(chunk_text: str) -> str:
    return chunk_text.split("\n", 1)[-1] if "\n" in chunk_text else chunk_text


def _first_sentence(text: str) -> str:
    return re.split(r"(?<=[.;])\s+", text.strip())[0]


def respond(system: str, user: str) -> dict:
    data = json.loads(user.split("\n\nYOUR PREVIOUS OUTPUT")[0])
    if system == prompts.PROFILER:
        out = []
        for c in data["CLAUSES"]:
            topics, sub, ot = heuristic_tag(c["text"])
            out.append({"id": c["id"], "topics": topics, "substantive": sub, "obligation_type": ot})
        return {"clauses": out, "profile": {"topics": ["record_keeping", "tipping_off"], "purpose": "AML policy", "defined_terms": ["Customer"]}}
    if system == prompts.QUERYGEN:
        return {"queries": ["pakistan aml regulations"]}
    if system == prompts.OBLIGATIONS:
        obs = []
        for ch in data["CHUNKS"]:
            for line in ch["text"].split("\n"):
                s = _first_sentence(line)
                if not re.search(r"\b(shall|must)\b", s):
                    continue
                obs.append({"chunk_id": ch["chunk_id"], "text": s, "quote": " ".join(s.split()[:20]),
                            "topic": (keyword_topics(s, 1) or ["other"])[0], "modality": "must"})
        return {"obligations": obs}
    if system == prompts.CONTEXT:
        return {"inferences": [{"text": "Supervisors focus on record retention.", "confidence": 0.6, "derived_from": []}]}
    if system == prompts.GAP:
        findings = []
        chunks = data["CHUNKS"]
        for c in data["CLAUSES"]:
            if "three years" in c["text"]:
                ch = next((x for x in chunks if "five years" in x["text"]), None)
                if ch:
                    m = re.search(r"[^.]*five years[^.]*", _body(ch["text"]))
                    findings.append({
                        "clause_ids": [c["id"]], "quote_from_policy": "for at least three years",
                        "gap_type": "CONTRADICTION", "severity": "high", "title": "Retention shorter than required",
                        "explanation": "Records must be kept for five years.",
                        "citations": [{"chunk_id": ch["chunk_id"], "quote": " ".join(m.group(0).split()[:20])}],
                    })
                # a fabricated citation that the verifier must reject
                findings.append({
                    "clause_ids": [c["id"]], "quote_from_policy": "retain records", "gap_type": "INSUFFICIENT",
                    "severity": "low", "title": "Fabricated", "explanation": "Not supported.",
                    "citations": [{"chunk_id": "nope:0000", "quote": "this text does not exist"}],
                })
        return {"findings": findings}
    if system == prompts.COVERAGE:
        items = []
        for o in data["OBLIGATIONS"]:
            missing = "disclose" in o["text"].lower()
            items.append({"obligation_id": o["obligation_id"], "status": "missing" if missing else "partial",
                          "clause_id": None, "title": "No tipping-off prohibition" if missing else "Partly covered",
                          "explanation": "Not addressed.", "severity": "high" if missing else "low"})
        return {"items": items}
    if system == prompts.VERIFIER:
        return {"results": [{"finding_id": c["finding_id"], "verdict": "SUPPORTED", "note": "ok"} for c in data["CLAIMS"]]}
    if system == prompts.REWRITER:
        return {"items": [{"finding_id": i["finding_id"], "text": "Revised clause text.", "rationale": "Aligns with the source."} for i in data["ITEMS"]]}
    raise AssertionError("unexpected prompt")


class FakeProvider:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def __call__(self, model: str, system: str, user: str, max_tokens: int, temperature: float) -> Completion:
        self.calls.append(system.split("TASK: ", 1)[1][:30])
        text = json.dumps(respond(system, user))
        return Completion(text=text, tokens_in=len(system + user) // 4, tokens_out=len(text) // 4)
