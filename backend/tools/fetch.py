"""Download a URL and extract clean text (trafilatura for HTML, pymupdf for PDF)."""
from __future__ import annotations

import asyncio
import re

from backend.schemas import ExtractedDoc
from backend.tools.parse import normalize_text, parse_pdf_bytes
from backend.tools.registry import content_hash

MAX_BYTES = 8 * 1024 * 1024
TIMEOUT = 25.0
UA = "Mozilla/5.0 (compatible; ComplAI/0.1; +https://github.com/Prox1ty/ComplAI)"


class FetchError(RuntimeError):
    pass


async def _download(url: str) -> tuple[bytes, str]:
    import httpx

    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True, headers={"User-Agent": UA}) as client:
        async with client.stream("GET", url) as r:
            if r.status_code >= 400:
                raise FetchError(f"HTTP {r.status_code} for {url}")
            size = int(r.headers.get("content-length") or 0)
            if size > MAX_BYTES:
                raise FetchError(f"{url} is larger than 8 MB")
            buf = bytearray()
            async for part in r.aiter_bytes():
                buf.extend(part)
                if len(buf) > MAX_BYTES:
                    raise FetchError(f"{url} is larger than 8 MB")
            return bytes(buf), r.headers.get("content-type", "")


def _extract_html(html: str, url: str) -> tuple[str, str, str | None]:
    import trafilatura

    text = trafilatura.extract(html, url=url, include_tables=True, include_comments=False, favor_precision=True) or ""
    title, date = "", None
    try:
        meta = trafilatura.extract_metadata(html)
        if meta is not None:
            title = meta.title or ""
            date = meta.date
    except Exception:  # noqa: BLE001
        pass
    if not title:
        m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
        title = re.sub(r"\s+", " ", m.group(1)).strip() if m else url
    return text, title, date


def _pdf_title_date(data: bytes) -> tuple[str, str | None]:
    import fitz

    with fitz.open(stream=data, filetype="pdf") as doc:
        md = doc.metadata or {}
        title = (md.get("title") or "").strip()
        raw = md.get("creationDate") or ""
    m = re.match(r"D:(\d{4})(\d{2})(\d{2})", raw)
    return title, (f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None)


async def fetch_and_extract(url: str) -> ExtractedDoc:
    data, ctype = await _download(url)
    is_pdf = "pdf" in ctype.lower() or url.lower().split("?")[0].endswith(".pdf") or data[:5] == b"%PDF-"
    if is_pdf:
        parsed = await asyncio.to_thread(parse_pdf_bytes, data)
        title, date = await asyncio.to_thread(_pdf_title_date, data)
        text, pages, kind = parsed.text, parsed.pages, "pdf"
        if not title:
            title = text.strip().split("\n", 1)[0][:200]
    else:
        html = data.decode("utf-8", errors="replace")
        raw, title, date = await asyncio.to_thread(_extract_html, html, url)
        text, pages, kind = normalize_text(raw), [], "html"
    if len(text.strip()) < 200:
        raise FetchError(f"no usable text extracted from {url}")
    return ExtractedDoc(
        url=url, title=title[:300], text=text, published_date=date, content_type=kind,
        content_hash=content_hash(text), pages=pages,
    )
