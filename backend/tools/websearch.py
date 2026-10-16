"""Web search: Tavily first, DuckDuckGo as fallback, cached for 7 days."""
from __future__ import annotations

import asyncio
import logging

from backend.cache import get_cache, make_key
from backend.config import settings
from backend.llm import current_usage
from backend.schemas import SearchHit

log = logging.getLogger(__name__)
TTL = 7 * 24 * 3600
TAVILY_URL = "https://api.tavily.com/search"


async def _tavily(query: str, k: int) -> list[SearchHit]:
    import httpx

    payload = {"query": query, "max_results": k, "search_depth": "basic", "include_answer": False, "api_key": settings.tavily_api_key}
    headers = {"Authorization": f"Bearer {settings.tavily_api_key}"}
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(TAVILY_URL, json=payload, headers=headers)
        r.raise_for_status()
        data = r.json()
    return [
        SearchHit(
            title=it.get("title") or it.get("url", ""),
            url=it["url"],
            snippet=(it.get("content") or "")[:500],
            published_date=it.get("published_date"),
        )
        for it in data.get("results", [])
        if it.get("url")
    ]


def _ddg_sync(query: str, k: int, country: str | None) -> list[SearchHit]:
    from duckduckgo_search import DDGS

    region = f"{country.lower()}-en" if country else "wt-wt"
    with DDGS() as ddgs:
        try:
            rows = list(ddgs.text(query, region=region, max_results=k))
        except Exception:
            rows = list(ddgs.text(query, max_results=k))
    return [SearchHit(title=r.get("title", ""), url=r.get("href", ""), snippet=r.get("body", "")[:500]) for r in rows if r.get("href")]


async def web_search(query: str, k: int = 6, country: str | None = None) -> list[SearchHit]:
    if not settings.web_search_enabled:
        return []
    cache = get_cache("search")
    key = make_key("search", query, k, country)
    hit = cache.get(key)
    if hit is not None:
        return [SearchHit(**h) for h in hit]
    usage = current_usage()
    if usage:
        usage.web_searches += 1
    results: list[SearchHit] = []
    if settings.tavily_api_key:
        try:
            results = await _tavily(query, k)
        except Exception as e:  # noqa: BLE001
            log.warning("tavily failed for %r: %s", query, e)
    if not results:
        try:
            results = await asyncio.to_thread(_ddg_sync, query, k, country)
        except Exception as e:  # noqa: BLE001
            log.warning("duckduckgo failed for %r: %s", query, e)
            results = []
    if results:
        cache.set(key, [r.model_dump() for r in results], expire=TTL)
    return results
