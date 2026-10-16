"""Test isolation: every test gets its own data dir, the memory vector store,
the hashing embedder and no network."""
from __future__ import annotations

import pytest

from backend import cache, llm
from backend.config import reload_settings
from backend.tools import registry, vectorstore


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("EMBED_BACKEND", "hash")
    monkeypatch.setenv("VECTOR_BACKEND", "memory")
    monkeypatch.setenv("WEB_SEARCH_ENABLED", "0")
    monkeypatch.setenv("LLM_TPM_LIMIT", "1000000")
    monkeypatch.setenv("LLM_RPM_LIMIT", "100000")
    monkeypatch.setenv("COVERAGE_HIGH", "0.9")
    monkeypatch.setenv("COVERAGE_LOW", "0.6")
    s = reload_settings()
    s.ensure_dirs()
    cache.reset_caches()
    vectorstore.reset_store()
    registry.reset_registry()
    llm.reset_budgeter()
    llm.set_provider(None)
    yield s
    llm.set_provider(None)
    registry.reset_registry()
    vectorstore.reset_store()
    cache.reset_caches()
