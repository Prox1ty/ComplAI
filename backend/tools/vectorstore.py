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
            _store = _ChromaStore() if settings.vector_backend == "chroma" else _MemoryStore()
        return _store


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


def hybrid_search(
    collection: str,
    query: str,
    filters: dict[str, Any] | None = None,
    k: int = 6,
    exclude_ids: set[str] | None = None,
    soft_topics: bool = True,
) -> list[Hit]:
    """Hybrid retrieval. ``filters`` keys are metadata equality / ``$in`` (list)
    filters, except ``topics`` which matches any overlap with the chunk's topics."""
    filters = dict(filters or {})
    topics = set(filters.pop("topics", None) or [])
    ids, docs, metas, embs, bm = _candidates(collection, filters)
    if not ids:
        return []

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

    qv = embed([query], "query")[0]
    dense_all = embs @ qv if embs.shape[1] == qv.shape[0] else np.zeros(len(ids))
    q_tokens = tokenize(query)
    bm_all = bm.get_scores(q_tokens) if (bm is not None and q_tokens) else np.zeros(len(ids))

    dense = {i: float(dense_all[i]) for i in idx}
    lex = {i: float(bm_all[i]) for i in idx}
    d_rank = {i: r for r, i in enumerate(sorted(idx, key=lambda i: -dense[i]))}
    l_rank = {i: r for r, i in enumerate(sorted(idx, key=lambda i: -lex[i]))}
    fused = {i: 1 / (RRF_K + d_rank[i] + 1) + (1 / (RRF_K + l_rank[i] + 1) if lex[i] > 0 else 0) for i in idx}

    hits: list[Hit] = []
    seen_norm: list[str] = []
    for i in sorted(idx, key=lambda i: -fused[i]):
        norm = " ".join(tokenize(docs[i]))
        if any(_similar(norm, s) >= 95 for s in seen_norm):
            continue
        seen_norm.append(norm)
        hits.append(Hit(id=ids[i], text=docs[i], metadata=metas[i], score=fused[i], dense=dense[i], bm25=lex[i]))
        if len(hits) >= k:
            break
    return hits
