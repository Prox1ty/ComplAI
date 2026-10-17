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


def _vec_store(isolated, monkeypatch):
    import pytest

    pytest.importorskip("sqlite_vec")
    monkeypatch.setattr(isolated, "vector_backend", "sqlite")
    vs.reset_store()
    st = vs.get_store()
    assert st.vec_ok, "sqlite-vec failed to load"
    return st


def test_sqlite_vec_knn_matches_exact_search(isolated, monkeypatch):
    st = _vec_store(isolated, monkeypatch)
    vs.vector_upsert(vs.FACTS, _chunks())
    vs.vector_upsert(vs.FACTS, _chunks())  # idempotent: rowids kept, no duplicate vectors
    assert st.conn.execute("SELECT COUNT(*) FROM vec_items").fetchone()[0] == 5
    q = "how long to keep transaction records"
    filt = {"jurisdiction": ["PK", "global"]}
    via_vec = vs.hybrid_search(vs.FACTS, q, filt, k=5)
    st.vec_ok = False  # force the exact numpy path on the same data
    exact = vs.hybrid_search(vs.FACTS, q, filt, k=5)
    same = {"f5": "f1"}  # f1 and f5 have identical text; dedupe may keep either
    assert [same.get(h.id, h.id) for h in via_vec] == [same.get(h.id, h.id) for h in exact]
    for a, b in zip(via_vec, exact):
        assert abs(a.dense - b.dense) < 1e-4  # cosine recovered from the L2 distance
    assert "vec" in vs.index_info() or "numpy" in vs.index_info()


def test_sqlite_vec_partitions_runs_and_deletes(isolated, monkeypatch):
    st = _vec_store(isolated, monkeypatch)
    for run in ("r1", "r2"):
        vs.vector_upsert(vs.CLAUSES, [
            Chunk(id=f"{run}:c1", text=f"{run} the bank shall keep records for five years", metadata={"run_id": run, "clause_id": "c1"}),
            Chunk(id=f"{run}:c2", text=f"{run} staff training happens every year", metadata={"run_id": run, "clause_id": "c2"}),
        ])
    hits = vs.hybrid_search(vs.CLAUSES, "record retention", {"run_id": "r1"}, k=5)
    assert {h.id for h in hits} == {"r1:c1", "r1:c2"}
    vs.vector_delete(vs.CLAUSES, {"run_id": "r1"})
    assert vs.hybrid_search(vs.CLAUSES, "record retention", {"run_id": "r1"}, k=5) == []
    assert st.conn.execute("SELECT COUNT(*) FROM vec_items").fetchone()[0] == 2
    assert vs.index_info().startswith("sqlite-vec")


def test_sqlite_vec_backfills_rows_from_plain_store(isolated, monkeypatch):
    import pytest

    pytest.importorskip("sqlite_vec")
    monkeypatch.setattr(isolated, "vector_backend", "sqlite-plain")
    vs.reset_store()
    vs.vector_upsert(vs.FACTS, _chunks())  # written without any vec index
    _vec_store(isolated, monkeypatch)  # reopen with sqlite-vec
    st = vs.get_store()
    assert st.conn.execute("SELECT COUNT(*) FROM vec_items").fetchone()[0] == 5
    hits = vs.hybrid_search(vs.FACTS, "politically exposed persons approval", {"jurisdiction": ["global"]}, k=1)
    assert [h.id for h in hits] == ["f2"]
