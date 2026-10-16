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


def test_sqlite_store_roundtrip_and_filters(isolated, monkeypatch):
    monkeypatch.setattr(isolated, "vector_backend", "sqlite")
    vs.reset_store()
    vs.vector_upsert(vs.FACTS, _chunks())
    vs.vector_upsert(vs.FACTS, _chunks())  # idempotent
    assert vs.count(vs.FACTS) == 5
    hits = vs.hybrid_search(vs.FACTS, "keep transaction records", {"jurisdiction": ["PK", "global"]}, k=5)
    assert "f4" not in [h.id for h in hits]
    assert vs.get_by_ids(vs.FACTS, ["f2"])["f2"].metadata["topics"] == ["pep"]
    vs.vector_delete(vs.FACTS, {"jurisdiction": "IN"})
    assert vs.count(vs.FACTS) == 4
    vs.reset_store()  # persisted on disk
    assert vs.count(vs.FACTS) == 4
    assert (isolated.data_dir / "vectors.sqlite").exists()


def test_migrates_regulatory_chunks_from_old_chroma_file(isolated, monkeypatch):
    import sqlite3

    chroma = isolated.data_dir / "chroma"
    chroma.mkdir(parents=True)
    c = sqlite3.connect(chroma / "chroma.sqlite3")
    c.executescript("""
        CREATE TABLE collections (id TEXT, name TEXT);
        CREATE TABLE segments (id TEXT, type TEXT, scope TEXT, collection TEXT);
        CREATE TABLE embeddings (id INTEGER PRIMARY KEY, segment_id TEXT, embedding_id TEXT);
        CREATE TABLE embedding_metadata (id INTEGER, key TEXT, string_value TEXT, int_value INTEGER,
                                         float_value REAL, bool_value INTEGER);
        INSERT INTO collections VALUES ('c1', 'regulatory_facts'), ('c2', 'policy_clauses');
        INSERT INTO segments VALUES ('m1', 'x', 'METADATA', 'c1'), ('v1', 'x', 'VECTOR', 'c1'), ('m2', 'x', 'METADATA', 'c2');
        INSERT INTO embeddings VALUES (1, 'm1', 'd:0000'), (2, 'm2', 'run:c1');
        INSERT INTO embedding_metadata VALUES
          (1, 'chroma:document', 'Records must be kept for five years.', NULL, NULL, NULL),
          (1, 'jurisdiction', 'PK', NULL, NULL, NULL),
          (1, 'topics', '|record_keeping|', NULL, NULL, NULL),
          (1, 'page', NULL, 3, NULL, NULL),
          (2, 'chroma:document', 'policy clause', NULL, NULL, NULL);
    """)
    c.commit()
    c.close()
    monkeypatch.setattr(isolated, "vector_backend", "sqlite")
    vs.reset_store()
    assert vs.count(vs.FACTS) == 1 and vs.count(vs.CLAUSES) == 0
    hit = vs.get_by_ids(vs.FACTS, ["d:0000"])["d:0000"]
    assert hit.metadata == {"jurisdiction": "PK", "topics": ["record_keeping"], "page": 3}
