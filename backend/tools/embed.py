"""Local embeddings with ``intfloat/multilingual-e5-small``.

E5 expects ``query: `` and ``passage: `` prefixes. The model is loaded once
(singleton). ``EMBED_BACKEND=hash`` switches to a deterministic hashing
embedder with the same interface, used by tests and offline smoke runs.
"""
from __future__ import annotations

import asyncio
import hashlib
import re
import threading
from typing import Literal

import numpy as np

from backend.config import settings

Kind = Literal["passage", "query"]
DIM_HASH = 384
BATCH = 32

_model = None
_lock = threading.Lock()
_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def _load_model():
    global _model
    with _lock:
        if _model is None:
            from sentence_transformers import SentenceTransformer

            _model = SentenceTransformer(settings.embed_model)
    return _model


def _hash_embed(texts: list[str]) -> np.ndarray:
    out = np.zeros((len(texts), DIM_HASH), dtype=np.float32)
    for i, t in enumerate(texts):
        toks = [w.lower() for w in _TOKEN_RE.findall(t)]
        feats = toks + [f"{a}_{b}" for a, b in zip(toks, toks[1:])]
        for f in feats:
            h = int.from_bytes(hashlib.md5(f.encode("utf-8")).digest()[:8], "little")
            out[i, h % DIM_HASH] += 1.0 if (h >> 63) & 1 else -1.0
        n = np.linalg.norm(out[i])
        if n > 0:
            out[i] /= n
    return out


def embed(texts: list[str], kind: Kind = "passage") -> np.ndarray:
    if not texts:
        return np.zeros((0, DIM_HASH), dtype=np.float32)
    if settings.embed_backend == "hash":
        return _hash_embed(texts)
    model = _load_model()
    prefixed = [f"{kind}: {t}" for t in texts]
    vecs = model.encode(prefixed, batch_size=BATCH, normalize_embeddings=True, show_progress_bar=False)
    return np.asarray(vecs, dtype=np.float32)


async def aembed(texts: list[str], kind: Kind = "passage") -> np.ndarray:
    return await asyncio.to_thread(embed, texts, kind)
