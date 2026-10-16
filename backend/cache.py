"""Thin wrapper around diskcache with an in-memory fallback.

Namespaces keep LLM responses and web search results apart. The fallback is
only used when diskcache is not installed (for example in a minimal test
environment); production installs get persistent caching.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from typing import Any

from backend.config import settings

try:
    import diskcache  # type: ignore
except ImportError:  # pragma: no cover
    diskcache = None

_lock = threading.Lock()
_caches: dict[str, Any] = {}


class _MemoryCache:
    def __init__(self) -> None:
        self._d: dict[str, tuple[float | None, Any]] = {}

    def get(self, key: str, default: Any = None) -> Any:
        item = self._d.get(key)
        if item is None:
            return default
        exp, val = item
        if exp is not None and exp < time.time():
            self._d.pop(key, None)
            return default
        return val

    def set(self, key: str, value: Any, expire: float | None = None) -> None:
        self._d[key] = (time.time() + expire if expire else None, value)

    def clear(self) -> None:
        self._d.clear()


def get_cache(namespace: str) -> Any:
    with _lock:
        if namespace not in _caches:
            if diskcache is not None:
                path = settings.cache_dir / namespace
                path.mkdir(parents=True, exist_ok=True)
                _caches[namespace] = diskcache.Cache(str(path))
            else:
                _caches[namespace] = _MemoryCache()
        return _caches[namespace]


def reset_caches() -> None:
    with _lock:
        for c in _caches.values():
            try:
                c.close()
            except Exception:
                pass
        _caches.clear()


def make_key(*parts: Any) -> str:
    raw = json.dumps(parts, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
