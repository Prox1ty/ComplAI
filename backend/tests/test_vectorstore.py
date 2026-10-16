from backend.schemas import Chunk
from backend.tools import vectorstore as vs


def _chunks():
    rows = [
        ("f1", "Banks must keep transaction records for at least five years.", "global", ["record_keeping"]),
        ("f2", "Senior management approval is required for politically exposed persons.", "global", ["pep"]),
        ("f3", "Suspicious transactions must be reported promptly to the FIU.", "PK", ["suspicious_reporting"]),
        ("f4", "Records of transactions must be kept for ten years.", "IN", ["record_keeping"]),
        ("f5", "Banks must keep transaction records for at least five years.", "PK", ["record_keeping"]),
    ]
    return [Chunk(id=i, text=t, metadata={"doc_id": i, "chunk_id": i, "jurisdiction": j, "topics": tp}) for i, t, j, tp in rows]


def test_upsert_is_idempotent_and_filters_apply_before_ranking():
    vs.vector_upsert(vs.FACTS, _chunks())
    vs.vector_upsert(vs.FACTS, _chunks())
    assert vs.count(vs.FACTS) == 5
    hits = vs.hybrid_search(vs.FACTS, "how long to keep transaction records", {"jurisdiction": ["PK", "global"]}, k=5)
    ids = [h.id for h in hits]
    assert "f4" not in ids  # other jurisdiction never ranked
    assert ids[0] in {"f1", "f5"}
    assert not ({"f1", "f5"} <= set(ids))  # near-identical text deduplicated


def test_topic_filter_soft_and_hard():
    vs.vector_upsert(vs.FACTS, _chunks())
    hits = vs.hybrid_search(vs.FACTS, "approval", {"jurisdiction": ["global"], "topics": ["pep"]}, k=1)
    assert [h.id for h in hits] == ["f2"]
    hard = vs.hybrid_search(vs.FACTS, "records", {"jurisdiction": ["global"], "topics": ["sanctions"]}, k=3, soft_topics=False)
    assert hard == []


def test_collections_are_separate():
    vs.vector_upsert(vs.FACTS, _chunks()[:1])
    vs.vector_upsert(vs.INFERENCES, [Chunk(id="i1", text="Supervisors focus on records.", metadata={"run_id": "r", "derived_from": ["f1"]})])
    assert vs.get_by_ids(vs.FACTS, ["i1"]) == {}
    got = vs.get_by_ids(vs.INFERENCES, ["i1"])["i1"]
    assert got.metadata["derived_from"] == ["f1"]
