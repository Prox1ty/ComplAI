"""Typed contracts.

The ``Result`` family is the contract with the frontend and is mirrored in
``frontend/src/types.ts``. The remaining models are internal data passed
between tools, agents and the orchestrator.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

GapType = Literal["CONTRADICTION", "INSUFFICIENT", "AMBIGUOUS", "MISSING", "OUTDATED"]
Severity = Literal["high", "medium", "low"]
VerificationStatus = Literal["verified", "partial", "unverified"]
Phase = Literal["parsing", "searching", "analysing", "verifying", "suggesting", "done", "error"]

SEVERITY_RANK: dict[str, int] = {"high": 3, "medium": 2, "low": 1}


# --------------------------------------------------------------------------
# Result contract (frontend)
# --------------------------------------------------------------------------
class Meta(BaseModel):
    country: str
    region: str | None = None
    city: str | None = None
    timezone: str
    as_of: str
    policy_type: str
    institution_type: str
    generated_at: str
    jurisdiction_chain: list[str] = Field(default_factory=list)


class Clause(BaseModel):
    id: str
    text: str
    start: int
    end: int
    section: str | None = None
    label: str | None = None


class PolicyDoc(BaseModel):
    filename: str
    full_text: str
    clauses: list[Clause]


class Span(BaseModel):
    start: int
    end: int


class Citation(BaseModel):
    doc_id: str
    chunk_id: str
    quote: str
    source_title: str
    source_url: str
    section: str | None = None


class Suggestion(BaseModel):
    text: str = ""
    rationale: str = ""


class Verification(BaseModel):
    status: VerificationStatus = "unverified"
    note: str | None = None


class Finding(BaseModel):
    id: str
    clause_ids: list[str]
    span: Span
    gap_type: GapType
    severity: Severity
    title: str
    explanation: str
    citations: list[Citation]
    suggestion: Suggestion = Field(default_factory=Suggestion)
    verification: Verification = Field(default_factory=Verification)
    inference_notes: list[str] = Field(default_factory=list)


class GapRow(BaseModel):
    finding_id: str
    clause_ref: str
    gap_type: GapType
    severity: Severity
    issue: str
    source: str
    fix: str


class Coverage(BaseModel):
    obligations_total: int = 0
    met: int = 0
    partial: int = 0
    missing: int = 0


class SourceRef(BaseModel):
    doc_id: str
    title: str
    issuer: str | None = None
    url: str
    jurisdiction: str


class Stats(BaseModel):
    tokens_in: int = 0
    tokens_out: int = 0
    llm_calls: int = 0
    duration_s: float = 0.0
    web_searches: int = 0
    cache_hits: int = 0
    reduced_mode: bool = False


class Result(BaseModel):
    run_id: str
    meta: Meta
    policy: PolicyDoc
    findings: list[Finding]
    gap_table: list[GapRow]
    coverage: Coverage
    sources: list[SourceRef]
    stats: Stats


class ProgressEvent(BaseModel):
    phase: Phase
    status: Literal["started", "progress", "completed", "failed"] = "progress"
    detail: str = ""
    progress: float = 0.0


# --------------------------------------------------------------------------
# Internal models
# --------------------------------------------------------------------------
class RunInputs(BaseModel):
    country: str
    region: str | None = None
    city: str | None = None
    timezone: str = "UTC"
    policy_type: str
    institution_type: str


class PageSpan(BaseModel):
    number: int
    start: int
    end: int


class ParsedDoc(BaseModel):
    text: str
    pages: list[PageSpan] = Field(default_factory=list)


class SearchHit(BaseModel):
    title: str
    url: str
    snippet: str = ""
    content: str | None = None
    score: float = 0.0
    published_date: str | None = None


class ExtractedDoc(BaseModel):
    url: str
    title: str
    text: str
    published_date: str | None = None
    content_type: str = "html"
    content_hash: str
    pages: list[PageSpan] = Field(default_factory=list)


class DocMeta(BaseModel):
    doc_id: str
    title: str
    issuer: str | None = None
    url: str
    jurisdiction: str
    topics: list[str] = Field(default_factory=list)
    language: str = "en"
    effective_date: str | None = None
    fetched_at: str | None = None
    content_hash: str | None = None
    obligations_json: str | None = None


class Chunk(BaseModel):
    id: str
    text: str
    metadata: dict[str, Any]


class Hit(BaseModel):
    id: str
    text: str
    metadata: dict[str, Any]
    score: float = 0.0
    dense: float = 0.0
    bm25: float = 0.0


class Obligation(BaseModel):
    id: str
    text: str
    topic: str
    modality: str = "must"
    chunk_id: str
    quote: str = ""
    doc_id: str = ""


class PolicyProfile(BaseModel):
    topics: list[str] = Field(default_factory=list)
    purpose: str = ""
    defined_terms: list[str] = Field(default_factory=list)


class ClauseTag(BaseModel):
    id: str
    topics: list[str] = Field(default_factory=list)
    substantive: bool = True
    obligation_type: Literal["must", "should", "prohibition", "definition", "other"] = "other"


class Inference(BaseModel):
    id: str
    text: str
    confidence: float = 0.5
    derived_from: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Human-in-the-loop: applying reviewer-approved fixes
# --------------------------------------------------------------------------
class FixSelection(BaseModel):
    finding_id: str
    text: str | None = None  # reviewer-edited wording; None = use the suggestion as is


class ApplyRequest(BaseModel):
    fixes: list[FixSelection] = Field(default_factory=list)


class AppliedChange(BaseModel):
    finding_id: str
    kind: Literal["replace", "insert"]
    start: int  # offsets into Revision.full_text
    end: int
    old_text: str
    new_text: str


class SkippedFix(BaseModel):
    finding_id: str | None = None
    reason: str
    conflicts_with: str | None = None


class Revision(BaseModel):
    run_id: str
    full_text: str
    changes: list[AppliedChange]
    skipped: list[SkippedFix]
    docx_url: str
    txt_url: str
    docx_from_original: bool = False
    unplaced: list[str] = Field(default_factory=list)
