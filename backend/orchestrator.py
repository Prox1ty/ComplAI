"""Deterministic pipeline (no LLM here):

P1 Parse -> P2 Search -> P3 Index/Context -> P4 Analyse -> P5 Verify -> P6 Suggest -> assemble Result.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from backend import llm
from backend.agents import context as context_agent
from backend.agents import gap, profiler, rewriter, search, verifier
from backend.agents.base import RunContext
from backend.agents.gap import Draft
from backend.config import ROOT
from backend.runs import RunStore
from backend.runs import store as default_store
from backend.schemas import (
    SEVERITY_RANK, Chunk, Coverage, GapRow, Meta, PolicyDoc, Result, RunInputs, SourceRef, Stats,
)
from backend.tools import sse
from backend.tools import vectorstore as vs
from backend.tools.clauses import split_clauses
from backend.tools.embed import aembed
from backend.tools.parse import parse_document
from backend.tools.registry import resolve_jurisdictions

log = logging.getLogger(__name__)


def compute_as_of(tz: str) -> tuple[str, str]:
    try:
        zone = ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        zone = ZoneInfo("UTC")
        tz = "UTC"
    now = datetime.now(zone)
    return now.date().isoformat(), tz


class Orchestrator:
    def __init__(self, run_id: str, inputs: RunInputs, file_path: Path, filename: str, store: RunStore | None = None) -> None:
        self.run_id = run_id
        self.inputs = inputs
        self.file_path = Path(file_path)
        self.filename = filename
        self.store = store or default_store

    async def emit(self, phase: str, status: str, detail: str, progress: float) -> None:
        await sse.emit(self.run_id, phase, status, detail, progress)

    async def run(self) -> Result | None:
        usage = llm.RunUsage()
        token = llm.set_usage(usage)
        t0 = time.monotonic()
        ctx: RunContext | None = None
        try:
            ctx, result = await self._pipeline(usage, t0)
            self.store.save_result(result, debug=self._debug(ctx, usage))
            await self.emit("done", "completed", f"Report ready: {len(result.findings)} finding(s)", 1.0)
            return result
        except Exception as e:  # noqa: BLE001
            log.exception("run %s failed", self.run_id)
            msg = str(e) if isinstance(e, ValueError) else f"The analysis failed: {e.__class__.__name__}: {e}"
            self.store.update(self.run_id, status="error", error=msg)
            try:
                self.store._write(self.run_id, "debug.json", self._debug(ctx, usage, error=msg))
            except Exception:  # noqa: BLE001
                pass
            await self.emit("error", "failed", msg, 0.0)
            return None
        finally:
            llm.reset_usage(token)

    def _debug(self, ctx: RunContext | None, usage: llm.RunUsage, error: str | None = None) -> dict:
        return {
            "run_id": self.run_id, "error": error, "llm_calls": usage.log, "failures": usage.failures,
            **(ctx.debug if ctx else {}),
        }

    async def _pipeline(self, usage: llm.RunUsage, t0: float) -> tuple[RunContext, Result]:
        inp = self.inputs
        llm.check_config()
        as_of, tz = compute_as_of(inp.timezone)
        inp.timezone = tz
        chain = resolve_jurisdictions(inp.country, inp.region, inp.city)

        # P1 parse ------------------------------------------------------------
        await self.emit("parsing", "started", f"Reading {self.filename}", 0.02)
        parsed = await asyncio.to_thread(parse_document, self.file_path)
        clauses = split_clauses(parsed.text)
        if not clauses:
            raise ValueError("No clauses could be found in the document.")
        ctx = RunContext(run_id=self.run_id, inputs=inp, chain=chain, as_of=as_of, clauses=clauses, emit=self.emit)
        await self.emit("parsing", "progress", f"Found {len(clauses)} clauses", 0.04)
        await profiler.run(ctx)
        await self.emit("parsing", "completed", f"{len(ctx.substantive)} substantive clauses", 0.1)

        # index the draft clauses for Pass B (reported under "searching")
        await self.emit("searching", "started", "Indexing policy clauses", 0.11)
        vs.vector_delete(vs.CLAUSES, {"run_id": self.run_id})
        cl_chunks = [
            Chunk(id=f"{self.run_id}:{c.id}", text=c.text, metadata={
                "run_id": self.run_id, "clause_id": c.id, "topics": getattr(ctx.tags.get(c.id), "topics", []),
                "start": c.start, "end": c.end, "substantive": bool(getattr(ctx.tags.get(c.id), "substantive", True)),
            })
            for c in clauses
        ]
        vs.vector_upsert(vs.CLAUSES, cl_chunks, await aembed([c.text for c in cl_chunks], "passage"))

        # P2 search + P3 context --------------------------------------------------
        await search.run(ctx)
        await context_agent.run(ctx)
        await self.emit("searching", "completed", f"{len(ctx.docs)} regulatory document(s) in scope", 0.38)

        # P4 analyse ------------------------------------------------------------
        drafts = await gap.pass_a(ctx)
        if usage.calls == 0 and usage.cache_hits == 0 and ctx.debug.get("errors"):
            # Every model call failed: report the cause instead of an empty "no gaps" report.
            first = ctx.debug["errors"][0].get("error", "unknown error")
            raise ValueError(f"The language model could not be used, so the policy was not analysed. First error: {first}")
        cov = await gap.pass_b(ctx)
        drafts.extend(cov.drafts)
        await self.emit("analysing", "completed", f"{len(drafts)} candidate finding(s)", 0.7)

        # P5 verify -------------------------------------------------------------
        kept = await verifier.run(ctx, drafts)
        await self.emit("verifying", "completed", f"{len(kept)} finding(s) verified", 0.85)

        # P6 suggest ------------------------------------------------------------
        await rewriter.run(ctx, kept)
        await self.emit("suggesting", "completed", "Suggestions drafted", 0.97)

        result = self._assemble(ctx, parsed.text, kept, cov, usage, time.monotonic() - t0, as_of)
        return ctx, result

    def _assemble(self, ctx: RunContext, text: str, drafts: list[Draft], cov: gap.CoverageResult,
                  usage: llm.RunUsage, duration: float, as_of: str) -> Result:
        drafts = _dedupe(drafts)
        drafts.sort(key=lambda d: (d.finding.span.start, -SEVERITY_RANK[d.finding.severity]))
        findings = []
        rows = []
        for i, d in enumerate(drafts, start=1):
            f = d.finding
            f.id = f"F{i}"
            findings.append(f)
            if f.gap_type == "MISSING":
                ref = f"After {d.section}" if d.section else "Not addressed"
            else:
                ref = ", ".join((c.label or c.id) for c in (ctx.clause(x) for x in f.clause_ids) if c)
            src = f.citations[0]
            rows.append(GapRow(
                finding_id=f.id, clause_ref=ref, gap_type=f.gap_type, severity=f.severity, issue=f.title,
                source=f"{src.source_title}{', ' + src.section.split(' > ')[-1] if src.section else ''}",
                fix=f.suggestion.text,
            ))
        cited = {c.doc_id for f in findings for c in f.citations}
        docs = sorted(ctx.docs, key=lambda d: (d.doc_id not in cited, d.title))
        inp = ctx.inputs
        return Result(
            run_id=self.run_id,
            meta=Meta(
                country=inp.country, region=inp.region or None, city=inp.city or None, timezone=inp.timezone,
                as_of=as_of, policy_type=inp.policy_type, institution_type=inp.institution_type,
                generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"), jurisdiction_chain=ctx.chain,
            ),
            policy=PolicyDoc(filename=self.filename, full_text=text, clauses=ctx.clauses),
            findings=findings,
            gap_table=rows,
            coverage=Coverage(obligations_total=cov.total, met=cov.met, partial=cov.partial, missing=cov.missing),
            sources=[SourceRef(doc_id=d.doc_id, title=d.title, issuer=d.issuer, url=d.url, jurisdiction=d.jurisdiction) for d in docs],
            stats=Stats(
                tokens_in=usage.tokens_in, tokens_out=usage.tokens_out, llm_calls=usage.calls,
                duration_s=round(duration, 1), web_searches=usage.web_searches, cache_hits=usage.cache_hits,
                reduced_mode=usage.reduced_mode,
            ),
        )


def _dedupe(drafts: list[Draft]) -> list[Draft]:
    """Drop findings that repeat the same span and gap type."""
    out: list[Draft] = []
    seen: set[tuple] = set()
    for d in sorted(drafts, key=lambda d: -SEVERITY_RANK[d.finding.severity]):
        f = d.finding
        if f.gap_type == "MISSING":  # the same omission found via several documents
            key = ("MISSING", " ".join(f.title.lower().split()))
        else:
            key = (f.span.start, f.span.end, f.gap_type, f.citations[0].chunk_id if f.citations else "")
        if key in seen:
            continue
        seen.add(key)
        out.append(d)
    return out


# --------------------------------------------------------------------------
# Fake pipeline (FAKE_PIPELINE=1): replays the mock report with timed phases.
# --------------------------------------------------------------------------
async def run_fake(run_id: str, inputs: RunInputs, filename: str, store: RunStore | None = None) -> Result:
    store = store or default_store
    script = [
        ("parsing", "started", f"Reading {filename}", 0.05), ("parsing", "completed", "Found 15 clauses", 0.1),
        ("searching", "started", "Checking the regulation registry", 0.15), ("searching", "progress", "Building regulatory context", 0.3),
        ("analysing", "started", "Reviewing group 1 of 4", 0.42), ("analysing", "progress", "Reviewing group 3 of 4", 0.58),
        ("analysing", "progress", "Coverage check: 14 obligations", 0.66), ("verifying", "started", "Checking citations", 0.75),
        ("suggesting", "started", "Drafting rewrites 1 of 2", 0.9),
    ]
    for phase, status, detail, p in script:
        await sse.emit(run_id, phase, status, detail, p)
        await asyncio.sleep(0.4)
    data = json.loads((ROOT / "frontend" / "mock" / "result.json").read_text(encoding="utf-8"))
    as_of, tz = compute_as_of(inputs.timezone)
    data["run_id"] = run_id
    data["meta"].update({
        "country": inputs.country, "region": inputs.region or None, "city": inputs.city or None, "timezone": tz,
        "as_of": as_of, "policy_type": inputs.policy_type, "institution_type": inputs.institution_type,
        "jurisdiction_chain": resolve_jurisdictions(inputs.country, inputs.region, inputs.city),
    })
    result = Result.model_validate(data)
    store.save_result(result, debug={"fake": True})
    await sse.emit(run_id, "done", "completed", "Report ready", 1.0)
    return result
