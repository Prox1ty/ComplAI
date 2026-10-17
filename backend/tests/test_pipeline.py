"""End-to-end run of the orchestrator on the sample policy with an offline
fake LLM, hashing embeddings and the in-memory vector store."""
import json
from pathlib import Path

from backend import llm
from backend.agents.search import ingest_document
from backend.orchestrator import Orchestrator
from backend.runs import RunStore
from backend.schemas import DocMeta, RunInputs
from backend.tools import sse
from backend.tools import vectorstore as vs
from backend.tools.registry import get_registry

from .fake_llm import FakeProvider

ROOT = Path(__file__).resolve().parents[2]

REG_A = """Section 1 Record keeping
Banks shall maintain all records of domestic and international transactions for at least five years after the date of the transaction.

Section 2 Confidentiality of reports
Banks and their staff shall not disclose to the customer or any third party that a suspicious transaction report has been filed.
"""
REG_B = """Part A Records
Every bank shall keep customer identification and transaction records for no less than five years following the end of the relationship.

Part B Reporting
A bank must not disclose the filing of a suspicious transaction report to any person.
"""


async def _seed():
    for doc_id, text in (("synthetic-a", REG_A), ("synthetic-b", REG_B)):
        meta = DocMeta(doc_id=doc_id, title=f"Synthetic regulation {doc_id[-1].upper()}", issuer="Test",
                       url=f"https://example.gov/{doc_id}", jurisdiction="global", topics=["record_keeping", "tipping_off"])
        await ingest_document(meta, text)


async def _run(store, fake, run_id):
    inputs = RunInputs(country="PK", region="Punjab", timezone="Asia/Karachi", policy_type="AML/KYC", institution_type="Commercial bank")
    orch = Orchestrator(run_id, inputs, ROOT / "samples" / "sample_aml_policy.txt", "sample_aml_policy.txt", store=store)
    return await orch.run()


async def test_end_to_end_with_fake_llm(isolated):
    fake = FakeProvider()
    llm.set_provider(fake)
    await _seed()
    assert get_registry().get_doc("synthetic-a").obligations_json  # extraction cached at ingest

    store = RunStore()
    result = await _run(store, fake, "run1")
    assert result is not None, json.dumps(sse.history("run1")[-1].model_dump())

    events = [e.phase for e in sse.history("run1")]
    for phase in ("parsing", "searching", "analysing", "verifying", "suggesting", "done"):
        assert phase in events

    titles = [f.title for f in result.findings]
    assert "Retention shorter than required" in titles
    assert "Fabricated" not in titles  # verifier dropped the bad citation
    text = result.policy.full_text
    ret = next(f for f in result.findings if f.title == "Retention shorter than required")
    assert text[ret.span.start:ret.span.end] == "for at least three years"
    assert ret.verification.status == "verified"
    assert ret.suggestion.text == "Revised clause text."
    missing = [f for f in result.findings if f.gap_type == "MISSING"]
    assert len(missing) == 1 and missing[0].span.start == missing[0].span.end  # deduped across docs
    # every citation points to a stored regulatory chunk whose text contains the quote
    for f in result.findings:
        assert f.citations
        for c in f.citations:
            assert c.chunk_id in vs.get_by_ids(vs.FACTS, [c.chunk_id])
    assert len(result.gap_table) == len(result.findings)
    assert result.coverage.obligations_total >= 2
    assert {s.doc_id for s in result.sources} == {"synthetic-a", "synthetic-b"}
    assert result.stats.web_searches == 0 and result.stats.llm_calls > 0
    assert (isolated.runs_dir / "run1" / "result.json").exists()
    debug = json.loads((isolated.runs_dir / "run1" / "debug.json").read_text())
    assert any(d.get("title") == "Fabricated" for d in debug["dropped"])

    # repeat run: no web searches, obligation extraction reused, prompts served from cache
    calls_before = len(fake.calls)
    again = await _run(store, fake, "run2")
    assert again is not None and again.stats.web_searches == 0
    assert not any(c.startswith("Extract the concrete") for c in fake.calls[calls_before:])
    assert again.stats.cache_hits > 0


async def test_bad_upload_reports_error(isolated, tmp_path):
    llm.set_provider(FakeProvider())
    empty = tmp_path / "empty.txt"
    empty.write_text("   ")
    inputs = RunInputs(country="PK", policy_type="AML/KYC", institution_type="Commercial bank")
    res = await Orchestrator("bad", inputs, empty, "empty.txt", store=RunStore()).run()
    assert res is None
    last = sse.history("bad")[-1]
    assert last.phase == "error" and "empty" in last.detail


async def test_run_fails_loudly_when_no_model_call_succeeds(isolated):
    from backend.llm import RetryableError

    async def down(*a):
        raise RetryableError("429", retry_after=3600)

    llm.set_provider(FakeProvider())
    await _seed()  # seeding works, then the model goes away
    llm.set_provider(down)
    res = await _run(RunStore(), None, "down")
    assert res is None
    last = sse.history("down")[-1]
    assert last.phase == "error" and "language model could not be used" in last.detail


async def test_config_error_stops_run_before_any_work(isolated, monkeypatch):
    from backend.config import settings

    llm.set_provider(None)
    monkeypatch.setattr(settings, "llm_provider", "nonsense")
    res = await _run(RunStore(), None, "cfg")
    assert res is None
    events = sse.history("cfg")
    assert [e.phase for e in events] == ["error"] and "LLM_PROVIDER" in events[0].detail
