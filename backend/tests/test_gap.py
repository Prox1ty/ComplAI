"""Retrieval and obligation-selection behaviour of the GapAnalysis agent."""
import json

from backend.agents import gap
from backend.agents.base import RunContext
from backend.schemas import Chunk, Clause, DocMeta, Obligation, RunInputs
from backend.tools import vectorstore as vs
from backend.tools.registry import get_registry


def _ctx(clauses=None):
    return RunContext(run_id="r", inputs=RunInputs(country="PK", policy_type="AML/KYC", institution_type="Commercial bank"),
                      chain=["PK", "global"], as_of="2026-10-17", clauses=clauses or [])


def test_each_clause_gets_its_own_evidence():
    facts = [
        ("a:1", "Records of transactions shall be kept for at least five years.", ["record_keeping"]),
        ("a:2", "Senior management approval is required before opening accounts for politically exposed persons.", ["pep"]),
        ("a:3", "Correspondent relationships with shell banks are prohibited.", ["correspondent_banking"]),
        ("b:1", "Suspicious transaction reports shall be filed promptly with the FMU portal.", ["suspicious_reporting"]),
    ]
    vs.vector_upsert(vs.FACTS, [Chunk(id=i, text=t, metadata={"doc_id": i[0], "jurisdiction": "PK", "topics": tp}) for i, t, tp in facts])
    group = [
        Clause(id="c1", text="The Bank keeps transaction records for three years.", start=0, end=1),
        Clause(id="c2", text="Politically exposed persons may be onboarded by branch staff.", start=1, end=2),
        Clause(id="c3", text="The Bank may open correspondent accounts with shell banks.", start=2, end=3),
    ]
    hits = gap.retrieve_for_group(_ctx(group), group, k=3)
    assert {h.id for h in hits} == {"a:1", "a:2", "a:3"}  # one best chunk per clause, not three for the "average" query


def test_obligations_are_interleaved_across_documents():
    reg = get_registry()
    for doc, n, modal in (("long-procedures", 50, "should"), ("core-regs", 10, "must")):
        reg.add_doc(DocMeta(doc_id=doc, title=doc, url=f"https://x/{doc}", jurisdiction="PK", topics=["record_keeping"]))
        obs = [Obligation(id=f"{doc}-o{i}", text=f"{doc} obligation {i}", topic="record_keeping", modality=modal,
                          chunk_id=f"{doc}:0000", doc_id=doc).model_dump() for i in range(n)]
        reg.set_obligations(doc, json.dumps(obs))
    ctx = _ctx()
    ctx.docs = reg.get_docs(["PK"])
    picked = gap.select_obligations(ctx, {"record_keeping"})
    assert len(picked) == gap.MAX_OBLIGATIONS
    assert sum(o.doc_id == "core-regs" for o in picked) == 10  # the short core document is fully covered
