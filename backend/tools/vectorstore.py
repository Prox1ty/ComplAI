"""Vector collections and hybrid (dense + BM25) retrieval.

Three collections share one embedder and are never mixed:
``regulatory_facts``, ``context_inferences`` and ``policy_clauses``.

``hybrid_search`` applies metadata filters *before* ranking: it loads the
filtered candidate set, scores it densely (cosine) and lexically (BM25),
merges with reciprocal rank fusion and removes near-duplicates.
"""
from __future__ import annotations

import json
import math
import re
import threading
from collections import Counter
from difflib import SequenceMatcher
from typing import Any

import numpy as np

from backend.config import settings
from backend.schemas import Chunk, Hit
from backend.tools.embed import embed

try:
    from rank_bm25 import BM25Okapi  # type: ignore
except ImportError:  # pragma: no cover
    BM25Okapi = None
try:
    from rapidfuzz import fuzz as _fuzz  # type: ignore
except ImportError:  # pragma: no cover
    _fuzz = None

FACTS = "regulatory_facts"
INFERENCES = "context_inferences"
CLAUSES = "policy_clauses"
COLLECTIONS = (FACTS, INFERENCES, CLAUSES)
LIST_KEYS = {"topics", "derived_from"}
RRF_K = 60
_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


# --------------------------------------------------------------------------
# metadata encoding (Chroma only stores scalars)
# --------------------------------------------------------------------------
def encode_meta(meta: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in meta.items():
        if v is None:
            continue
        if k in LIST_KEYS or isinstance(v, (list, tuple, set)):
            out[k] = "|" + "|".join(str(x) for x in v) + "|"
        elif isinstance(v, (str, int, float, bool)):
            out[k] = v
        else:
            out[k] = json.dumps(v, default=str)
    return out


def decode_meta(meta: dict[str, Any] | None) -> dict[str, Any]:
    out = dict(meta or {})
    for k in LIST_KEYS:
        v = out.get(k)
        if isinstance(v, str):
            out[k] = [x for x in v.strip("|").split("|") if x]
    return out


# --------------------------------------------------------------------------
# stores
# --------------------------------------------------------------------------
class _MemoryStore:
    def __init__(self) -> None:
        self.data: dict[str, dict[str, dict[str, Any]]] = {c: {} for c in COLLECTIONS}

    def upsert(self, col: str, ids, docs, metas, embs) -> None:
        d = self.data.setdefault(col, {})
        for i, doc, m, e in zip(ids, docs, metas, embs):
            d[i] = {"doc": doc, "meta": m, "emb": np.asarray(e, dtype=np.float32)}

    def get(self, col: str, where: dict[str, Any] | None = None, ids: list[str] | None = None):
        d = self.data.setdefault(col, {})
        items = [(i, d[i]) for i in ids if i in d] if ids is not None else list(d.items())
        rows = [(i, r) for i, r in items if _match_scalar(r["meta"], where)]
        return (
            [i for i, _ in rows],
            [r["doc"] for _, r in rows],
            [r["meta"] for _, r in rows],
            np.stack([r["emb"] for _, r in rows]) if rows else np.zeros((0, 1), dtype=np.float32),
        )

    def delete(self, col: str, where: dict[str, Any]) -> None:
        d = self.data.setdefault(col, {})
        for i in [i for i, r in d.items() if _match_scalar(r["meta"], where)]:
            d.pop(i)

    def count(self, col: str) -> int:
        return len(self.data.setdefault(col, {}))


class _SqliteStore:
    """Default store: one SQLite file (``data/vectors.sqlite``) holding text,
    metadata and float32 embeddings. Ranking happens in ``hybrid_search``, so
    no ANN index is needed; this avoids the on-disk index files that Chroma
    keeps (and that cloud-synced folders such as OneDrive can corrupt)."""

    def __init__(self, path=None) -> None:
        import sqlite3

        self.path = path or (settings.data_dir / "vectors.sqlite")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS vectors (collection TEXT NOT NULL, id TEXT NOT NULL, doc TEXT NOT NULL,"
            " meta TEXT NOT NULL, emb BLOB NOT NULL, PRIMARY KEY (collection, id))"
        )
        self.conn.commit()
        self.lock = threading.Lock()

    def upsert(self, col: str, ids, docs, metas, embs) -> None:
        rows = [
            (col, i, d, json.dumps(m, ensure_ascii=False), np.asarray(e, dtype=np.float32).tobytes())
            for i, d, m, e in zip(ids, docs, metas, embs)
        ]
        with self.lock:
            # ON CONFLICT ... DO UPDATE keeps each row's rowid stable (the vec index keys on it)
            self.conn.executemany(
                "INSERT INTO vectors (collection, id, doc, meta, emb) VALUES (?,?,?,?,?) "
                "ON CONFLICT(collection, id) DO UPDATE SET doc=excluded.doc, meta=excluded.meta, emb=excluded.emb",
                rows,
            )
            self.conn.commit()

    def _rows(self, col: str, ids: list[str] | None):
        with self.lock:
            if ids is None:
                return self.conn.execute("SELECT id, doc, meta, emb FROM vectors WHERE collection=?", (col,)).fetchall()
            out = []
            for s in range(0, len(ids), 500):
                part = ids[s:s + 500]
                q = f"SELECT id, doc, meta, emb FROM vectors WHERE collection=? AND id IN ({','.join('?' * len(part))})"
                out.extend(self.conn.execute(q, (col, *part)).fetchall())
            return out

    def get(self, col: str, where: dict[str, Any] | None = None, ids: list[str] | None = None):
        rows = []
        for i, d, m, e in self._rows(col, ids):
            meta = json.loads(m)
            if _match_scalar(meta, where):
                rows.append((i, d, meta, np.frombuffer(e, dtype=np.float32)))
        if not rows:
            return [], [], [], np.zeros((0, 1), dtype=np.float32)
        dims = {len(r[3]) for r in rows}
        if len(dims) > 1:  # embedder changed (e.g. hash vs model); keep the majority dimension
            dim = max(dims, key=lambda d: sum(1 for r in rows if len(r[3]) == d))
            rows = [r for r in rows if len(r[3]) == dim]
        return [r[0] for r in rows], [r[1] for r in rows], [r[2] for r in rows], np.stack([r[3] for r in rows])

    def delete(self, col: str, where: dict[str, Any]) -> None:
        ids, _, _, _ = self.get(col, where)
        with self.lock:
            for s in range(0, len(ids), 500):
                part = ids[s:s + 500]
                self.conn.execute(
                    f"DELETE FROM vectors WHERE collection=? AND id IN ({','.join('?' * len(part))})", (col, *part)
                )
            self.conn.commit()

    def count(self, col: str) -> int:
        with self.lock:
            return self.conn.execute("SELECT COUNT(*) FROM vectors WHERE collection=?", (col,)).fetchone()[0]


VEC_MAX_K = 4096  # sqlite-vec's upper bound for k in a KNN query


def partition_for(collection: str, meta: dict[str, Any]) -> str:
    """Per-run collections are partitioned by run so a KNN never scans other runs."""
    if collection == FACTS:
        return collection
    return f"{collection}:{meta.get('run_id', '')}"


class _SqliteVecStore(_SqliteStore):
    """``_SqliteStore`` plus a sqlite-vec ``vec0`` index for nearest-neighbour search.

    Text, metadata and a copy of each embedding stay in ``vectors``; the
    ``vec_items`` virtual table holds the vectors keyed by the same rowid and
    partitioned by collection (and run, for per-run collections). If the
    extension cannot be loaded, ``vec_ok`` is False and search falls back to
    exact numpy scoring over the stored embeddings.
    """

    def __init__(self, path=None) -> None:
        super().__init__(path)
        self.vec_ok = False
        self.vec_error: str | None = None
        self.vec_version: str | None = None
        self.dim: int | None = None
        try:
            import sqlite_vec  # type: ignore

            self.conn.enable_load_extension(True)
            sqlite_vec.load(self.conn)
            self.conn.enable_load_extension(False)
            self.vec_version = self.conn.execute("SELECT vec_version()").fetchone()[0]
            self.vec_ok = True
        except Exception as e:  # noqa: BLE001 - missing package, or Python built without extension loading
            import logging

            self.vec_error = f"{type(e).__name__}: {e}"

            logging.getLogger(__name__).warning("sqlite-vec unavailable (%s); using exact numpy search", e)
            return
        self.conn.execute("CREATE TABLE IF NOT EXISTS vec_meta (key TEXT PRIMARY KEY, value TEXT)")
        row = self.conn.execute("SELECT value FROM vec_meta WHERE key='dim'").fetchone()
        self.dim = int(row[0]) if row else None
        self.conn.commit()
        self._backfill()

    def _ensure_index(self, dim: int) -> None:
        if self.dim == dim:
            return
        if self.dim is not None:
            raise ValueError(
                f"Embedding size changed from {self.dim} to {dim}. Delete data/vectors.sqlite and re-ingest "
                "(EMBED_MODEL must stay the same for an existing store)."
            )
        self.conn.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS vec_items USING vec0(embedding float[{dim}], part text partition key)"
        )
        self.conn.execute("INSERT OR REPLACE INTO vec_meta VALUES ('dim', ?)", (str(dim),))
        self.dim = dim

    def _backfill(self) -> None:
        """Index rows written before sqlite-vec was enabled (e.g. by the plain SQLite store)."""
        with self.lock:
            if self.dim is None:
                first = self.conn.execute("SELECT emb FROM vectors LIMIT 1").fetchone()
                if not first:
                    return
                self._ensure_index(len(first[0]) // 4)
            todo = self.conn.execute(
                "SELECT rowid, collection, meta, emb FROM vectors WHERE rowid NOT IN (SELECT rowid FROM vec_items)"
            ).fetchall()
            rows = [
                (rid, emb, partition_for(col, json.loads(meta)))
                for rid, col, meta, emb in todo
                if len(emb) // 4 == self.dim
            ]
            self.conn.executemany("INSERT INTO vec_items(rowid, embedding, part) VALUES (?,?,?)", rows)
            self.conn.commit()
        if rows:
            import logging

            logging.getLogger(__name__).info("indexed %d existing vectors in sqlite-vec", len(rows))

    def upsert(self, col: str, ids, docs, metas, embs) -> None:
        super().upsert(col, ids, docs, metas, embs)
        if not self.vec_ok or not len(ids):
            return
        embs = np.asarray(embs, dtype=np.float32)
        with self.lock:
            self._ensure_index(int(embs.shape[1]))
            rowids = self._rowids(col, list(ids))
            rows = [(rowids[i], e.tobytes(), partition_for(col, m)) for i, m, e in zip(ids, metas, embs)]
            self.conn.executemany("DELETE FROM vec_items WHERE rowid = ?", [(r[0],) for r in rows])
            self.conn.executemany("INSERT INTO vec_items(rowid, embedding, part) VALUES (?,?,?)", rows)
            self.conn.commit()

    def _rowids(self, col: str, ids: list[str]) -> dict[str, int]:
        out: dict[str, int] = {}
        for s in range(0, len(ids), 500):
            part = ids[s:s + 500]
            q = f"SELECT id, rowid FROM vectors WHERE collection=? AND id IN ({','.join('?' * len(part))})"
            out.update(dict(self.conn.execute(q, (col, *part)).fetchall()))
        return out

    def delete(self, col: str, where: dict[str, Any]) -> None:
        if self.vec_ok and self.dim is not None:
            ids, _, _, _ = self.get(col, where)
            with self.lock:
                rowids = list(self._rowids(col, ids).values())
                self.conn.executemany("DELETE FROM vec_items WHERE rowid = ?", [(r,) for r in rowids])
                self.conn.commit()
        super().delete(col, where)

    def knn(self, part: str, qv: np.ndarray, k: int = VEC_MAX_K) -> list[tuple[str, str, dict, float]]:
        """Nearest neighbours in one partition: [(id, doc, encoded_meta, l2_distance)], closest first."""
        if not self.vec_ok or self.dim is None or len(qv) != self.dim:
            return []
        with self.lock:
            pairs = self.conn.execute(
                "SELECT rowid, distance FROM vec_items WHERE embedding MATCH ? AND k = ? AND part = ?",
                (np.asarray(qv, dtype=np.float32).tobytes(), min(k, VEC_MAX_K), part),
            ).fetchall()
            if not pairs:
                return []
            rows: dict[int, tuple] = {}
            rids = [r for r, _ in pairs]
            for s in range(0, len(rids), 500):
                chunk = rids[s:s + 500]
                q = f"SELECT rowid, id, doc, meta FROM vectors WHERE rowid IN ({','.join('?' * len(chunk))})"
                rows.update({r[0]: r[1:] for r in self.conn.execute(q, chunk).fetchall()})
        return [(rows[r][0], rows[r][1], json.loads(rows[r][2]), float(d)) for r, d in pairs if r in rows]


def migrate_from_chroma(store: "_SqliteStore", chroma_db=None) -> int:
    """Copy regulatory chunks out of an old Chroma database into ``store``.

    Reads ``chroma.sqlite3`` directly (no chromadb import, no HNSW files) and
    re-embeds the text, so it also works when Chroma's index files are broken.
    Only ``regulatory_facts`` is migrated; the other collections are per run.
    """
    import sqlite3

    path = chroma_db or (settings.data_dir / "chroma" / "chroma.sqlite3")
    if not path.exists() or store.count(FACTS):
        return 0
    try:
        c = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        seg = c.execute(
            "SELECT s.id FROM segments s JOIN collections col ON col.id = s.collection "
            "WHERE col.name = ? AND s.scope = 'METADATA'", (FACTS,)
        ).fetchone()
        if not seg:
            return 0
        rows = c.execute(
            "SELECT e.embedding_id, m.key, m.string_value, m.int_value, m.float_value, m.bool_value "
            "FROM embeddings e JOIN embedding_metadata m ON m.id = e.id WHERE e.segment_id = ?", (seg[0],)
        ).fetchall()
        c.close()
    except sqlite3.Error:
        return 0
    recs: dict[str, dict[str, Any]] = {}
    for eid, key, sv, iv, fv, bv in rows:
        val = sv if sv is not None else iv if iv is not None else fv if fv is not None else (bool(bv) if bv is not None else None)
        if val is not None:
            recs.setdefault(eid, {})[key] = val
    items = [(i, m.pop("chroma:document"), m) for i, m in recs.items() if "chroma:document" in m]
    if not items:
        return 0
    items.sort(key=lambda x: x[0])
    docs = [d for _, d, _ in items]
    embs = embed(docs, "passage")
    store.upsert(FACTS, [i for i, _, _ in items], docs, [m for _, _, m in items], embs)
    return len(items)


class _ChromaStore:
    def __init__(self) -> None:
        import chromadb

        path = settings.data_dir / "chroma"
        path.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=str(path))
        self.cols = {c: self.client.get_or_create_collection(c) for c in COLLECTIONS}

    def _col(self, col: str):
        if col not in self.cols:
            self.cols[col] = self.client.get_or_create_collection(col)
        return self.cols[col]

    def upsert(self, col: str, ids, docs, metas, embs) -> None:
        c = self._col(col)
        step = 500
        for s in range(0, len(ids), step):
            c.upsert(
                ids=list(ids[s:s + step]),
                documents=list(docs[s:s + step]),
                metadatas=list(metas[s:s + step]),
                embeddings=[list(map(float, e)) for e in embs[s:s + step]],
            )

    def get(self, col: str, where: dict[str, Any] | None = None, ids: list[str] | None = None):
        c = self._col(col)
        kwargs: dict[str, Any] = {"include": ["documents", "metadatas", "embeddings"]}
        cw = _chroma_where(where)
        if cw:
            kwargs["where"] = cw
        if ids is not None:
            if not ids:
                return [], [], [], np.zeros((0, 1), dtype=np.float32)
            kwargs["ids"] = ids
        res = c.get(**kwargs)
        embs = res.get("embeddings")
        arr = np.asarray(embs, dtype=np.float32) if embs is not None and len(embs) else np.zeros((0, 1), dtype=np.float32)
        return list(res["ids"]), list(res["documents"] or []), list(res["metadatas"] or []), arr

    def delete(self, col: str, where: dict[str, Any]) -> None:
        cw = _chroma_where(where)
        if cw:
            self._col(col).delete(where=cw)

    def count(self, col: str) -> int:
        return self._col(col).count()


def _chroma_where(where: dict[str, Any] | None) -> dict[str, Any] | None:
    if not where:
        return None
    conds = []
    for k, v in where.items():
        if isinstance(v, (list, tuple, set)):
            vals = list(v)
            conds.append({k: {"$in": vals}} if len(vals) != 1 else {k: vals[0]})
        else:
            conds.append({k: v})
    return conds[0] if len(conds) == 1 else {"$and": conds}


def _match_scalar(meta: dict[str, Any], where: dict[str, Any] | None) -> bool:
    for k, v in (where or {}).items():
        mv = meta.get(k)
        if isinstance(v, (list, tuple, set)):
            if mv not in v:
                return False
        elif mv != v:
            return False
    return True


_store = None
_store_lock = threading.Lock()
_versions: dict[str, int] = {c: 0 for c in COLLECTIONS}
_index_cache: dict[tuple, Any] = {}


def get_store():
    global _store
    with _store_lock:
        if _store is None:
            if settings.vector_backend == "chroma":
                _store = _ChromaStore()
            elif settings.vector_backend == "memory":
                _store = _MemoryStore()
            else:
                _store = _SqliteStore() if settings.vector_backend == "sqlite-plain" else _SqliteVecStore()
                n = migrate_from_chroma(_store)
                if n:
                    import logging

                    logging.getLogger(__name__).info("migrated %d regulatory chunks from the old Chroma store", n)
        return _store


def index_info() -> str:
    """Human-readable description of the active vector search, for /api/health."""
    st = get_store()
    if getattr(st, "vec_ok", False):
        return f"sqlite-vec {st.vec_version}"
    why = getattr(st, "vec_error", None)
    return f"{type(st).__name__.strip('_')} (exact numpy search{': ' + why if why else ''})"


def reset_store() -> None:
    global _store
    with _store_lock:
        _store = None
        _index_cache.clear()
        for c in list(_versions):
            _versions[c] += 1


def _bump(col: str) -> None:
    _versions[col] = _versions.get(col, 0) + 1
    for key in [k for k in _index_cache if k[0] == col]:
        _index_cache.pop(key, None)


# --------------------------------------------------------------------------
# public API
# --------------------------------------------------------------------------
def vector_upsert(collection: str, chunks: list[Chunk], embeddings: np.ndarray | None = None) -> int:
    """Idempotent upsert keyed on chunk id. Embeds passages if no embeddings are given."""
    if not chunks:
        return 0
    if embeddings is None:
        embeddings = embed([c.text for c in chunks], "passage")
    get_store().upsert(
        collection,
        [c.id for c in chunks],
        [c.text for c in chunks],
        [encode_meta(c.metadata) for c in chunks],
        embeddings,
    )
    _bump(collection)
    return len(chunks)


def vector_delete(collection: str, where: dict[str, Any]) -> None:
    get_store().delete(collection, where)
    _bump(collection)


def get_by_ids(collection: str, ids: list[str]) -> dict[str, Hit]:
    if not ids:
        return {}
    rid, docs, metas, _ = get_store().get(collection, ids=list(dict.fromkeys(ids)))
    return {i: Hit(id=i, text=d, metadata=decode_meta(m)) for i, d, m in zip(rid, docs, metas)}


def count(collection: str) -> int:
    return get_store().count(collection)


def tokenize(s: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(s)]


class _SimpleBM25:  # pragma: no cover - fallback when rank_bm25 is missing
    def __init__(self, corpus: list[list[str]], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self.docs = [Counter(d) for d in corpus]
        self.lens = [len(d) for d in corpus]
        self.avg = (sum(self.lens) / len(self.lens)) if self.lens else 0
        df: Counter = Counter()
        for d in corpus:
            df.update(set(d))
        n = len(corpus)
        self.idf = {t: math.log((n - f + 0.5) / (f + 0.5) + 1) for t, f in df.items()}

    def get_scores(self, q: list[str]) -> np.ndarray:
        out = np.zeros(len(self.docs))
        for i, (tf, ln) in enumerate(zip(self.docs, self.lens)):
            s = 0.0
            for t in q:
                f = tf.get(t, 0)
                if f:
                    s += self.idf.get(t, 0) * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * ln / (self.avg or 1)))
            out[i] = s
        return out


def _bm25(corpus: list[list[str]]):
    return (BM25Okapi or _SimpleBM25)(corpus) if corpus else None


def _similar(a: str, b: str) -> float:
    if _fuzz is not None:
        return float(_fuzz.ratio(a, b))
    return SequenceMatcher(None, a, b, autojunk=False).ratio() * 100


def _candidates(collection: str, where: dict[str, Any] | None):
    key = (collection, json.dumps(where or {}, sort_keys=True, default=str), _versions.get(collection, 0))
    cached = _index_cache.get(key)
    if cached is None:
        ids, docs, metas, embs = get_store().get(collection, where=where or None)
        metas = [decode_meta(m) for m in metas]
        cached = (ids, docs, metas, embs, _bm25([tokenize(d) for d in docs]))
        if len(_index_cache) > 64:
            _index_cache.clear()
        _index_cache[key] = cached
    return cached


def _fuse(ids, docs, metas, dense: np.ndarray, bm, query: str, topics: set[str], k: int,
          exclude_ids: set[str] | None, soft_topics: bool) -> list[Hit]:
    """Topic/exclusion selection, BM25, reciprocal rank fusion and near-duplicate removal."""

    def select(use_topics: bool) -> list[int]:
        out = []
        for i, m in enumerate(metas):
            if exclude_ids and ids[i] in exclude_ids:
                continue
            if use_topics and topics and not (set(m.get("topics") or []) & topics):
                continue
            out.append(i)
        return out

    idx = select(True)
    if topics and soft_topics and len(idx) < k:
        idx = select(False)
    if not idx:
        return []

    q_tokens = tokenize(query)
    bm_all = bm.get_scores(q_tokens) if (bm is not None and q_tokens) else np.zeros(len(ids))
    dense_d = {i: float(dense[i]) for i in idx}
    lex = {i: float(bm_all[i]) for i in idx}
    d_rank = {i: r for r, i in enumerate(sorted(idx, key=lambda i: -dense_d[i]))}
    l_rank = {i: r for r, i in enumerate(sorted(idx, key=lambda i: -lex[i]))}
    fused = {i: 1 / (RRF_K + d_rank[i] + 1) + (1 / (RRF_K + l_rank[i] + 1) if lex[i] > 0 else 0) for i in idx}

    hits: list[Hit] = []
    seen_norm: list[str] = []
    for i in sorted(idx, key=lambda i: -fused[i]):
        norm = " ".join(tokenize(docs[i]))
        if any(_similar(norm, s) >= 95 for s in seen_norm):
            continue
        seen_norm.append(norm)
        hits.append(Hit(id=ids[i], text=docs[i], metadata=metas[i], score=fused[i], dense=dense_d[i], bm25=lex[i]))
        if len(hits) >= k:
            break
    return hits


def _vec_partition(collection: str, filters: dict[str, Any]) -> str | None:
    if collection == FACTS:
        return FACTS
    run = filters.get("run_id")
    return f"{collection}:{run}" if isinstance(run, str) else None


def hybrid_search(
    collection: str,
    query: str,
    filters: dict[str, Any] | None = None,
    k: int = 6,
    exclude_ids: set[str] | None = None,
    soft_topics: bool = True,
) -> list[Hit]:
    """Hybrid retrieval. ``filters`` keys are metadata equality / ``$in`` (list)
    filters, except ``topics`` which matches any overlap with the chunk's topics.

    With sqlite-vec the dense side is a KNN query on the ``vec0`` index (one
    partition per collection/run); otherwise it is exact numpy scoring."""
    filters = dict(filters or {})
    topics = set(filters.pop("topics", None) or [])
    store = get_store()
    qv = embed([query], "query")[0]

    part = _vec_partition(collection, filters)
    if getattr(store, "vec_ok", False) and part is not None:
        rows = [r for r in store.knn(part, qv) if _match_scalar(r[2], filters)]
        if not rows:
            return []
        ids = [r[0] for r in rows]
        docs = [r[1] for r in rows]
        metas = [decode_meta(r[2]) for r in rows]
        # unit vectors: cosine = 1 - L2^2 / 2
        dense = np.array([1.0 - (r[3] ** 2) / 2.0 for r in rows], dtype=np.float32)
        return _fuse(ids, docs, metas, dense, _bm25([tokenize(d) for d in docs]), query, topics, k, exclude_ids, soft_topics)

    ids, docs, metas, embs, bm = _candidates(collection, filters)
    if not ids:
        return []
    dense = embs @ qv if embs.shape[1] == qv.shape[0] else np.zeros(len(ids))
    return _fuse(ids, docs, metas, dense, bm, query, topics, k, exclude_ids, soft_topics)
