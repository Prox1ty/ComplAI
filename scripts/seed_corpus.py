"""Ingest the seed corpus (corpus/*.pdf|txt|md + sidecar .json) into the registry,
the regulatory_facts collection and SQLite, then extract obligations.

    python scripts/seed_corpus.py                # ingest what is in corpus/
    python scripts/seed_corpus.py --download     # first fetch PDFs listed in sidecars
    python scripts/seed_corpus.py --no-extract   # index only, skip LLM obligation extraction
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend import llm  # noqa: E402
from backend.agents.search import ingest_document  # noqa: E402
from backend.config import settings  # noqa: E402
from backend.schemas import DocMeta  # noqa: E402
from backend.taxonomy import normalize_topics  # noqa: E402
from backend.tools.obligations import obligation_extractor  # noqa: E402
from backend.tools.parse import normalize_text, parse_pdf_bytes  # noqa: E402
from backend.tools.registry import content_hash, doc_id_for_bytes, get_registry  # noqa: E402

CORPUS = ROOT / "corpus"
EXTS = (".pdf", ".txt", ".md")


async def download(sidecar: Path, meta: dict) -> None:
    import httpx

    url = meta.get("download_url")
    target = sidecar.with_suffix(".pdf")
    if not url or any(sidecar.with_suffix(e).exists() for e in EXTS):
        return
    print(f"downloading {url}")
    try:
        async with httpx.AsyncClient(timeout=120, follow_redirects=True, headers={"User-Agent": "ComplAI seed"}) as c:
            r = await c.get(url)
            r.raise_for_status()
        if not r.content.startswith(b"%PDF"):
            print(f"  ! {url} did not return a PDF; save it manually as {target.name}")
            return
        target.write_bytes(r.content)
        print(f"  saved {target.name} ({len(r.content) // 1024} KB)")
    except Exception as e:  # noqa: BLE001
        print(f"  ! download failed: {e}. Save the PDF manually as {target.name}")


async def ingest(path: Path, meta: dict, extract: bool) -> None:
    data = path.read_bytes()
    if path.suffix.lower() == ".pdf":
        parsed = parse_pdf_bytes(data)
        text, pages = parsed.text, [p.model_dump() for p in parsed.pages]
    else:
        text, pages = normalize_text(data.decode("utf-8", errors="replace")), None
    doc_id = doc_id_for_bytes(data)
    reg = get_registry()
    existing = reg.get_doc(doc_id)
    if existing and existing.content_hash == content_hash(text):
        print(f"= {path.name} already indexed ({doc_id[:10]})")
    else:
        dm = DocMeta(
            doc_id=doc_id, title=meta["title"], issuer=meta.get("issuer"), url=meta.get("url", ""),
            jurisdiction=meta.get("jurisdiction", "global"), topics=normalize_topics(meta.get("topics")),
            language=meta.get("language", "en"), effective_date=meta.get("effective_date"),
            fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        n = await ingest_document(dm, text, pages, extract=False)
        print(f"+ {path.name}: {n} chunks under '{dm.jurisdiction}' ({doc_id[:10]})")
    if extract:
        usage = llm.RunUsage(ceiling=10_000_000)
        tok = llm.set_usage(usage)
        try:
            obs = await obligation_extractor(doc_id)
        finally:
            llm.reset_usage(tok)
        print(f"  obligations: {len(obs)} (tokens used: {usage.total})")


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--download", action="store_true", help="fetch PDFs listed as download_url in sidecars")
    ap.add_argument("--no-extract", action="store_true", help="skip obligation extraction (no LLM calls)")
    args = ap.parse_args()
    settings.ensure_dirs()
    sidecars = sorted(CORPUS.glob("*.json"))
    if not sidecars:
        print("no sidecar .json files in corpus/")
        return
    for sc in sidecars:
        meta = json.loads(sc.read_text(encoding="utf-8"))
        if args.download:
            await download(sc, meta)
        doc = next((sc.with_suffix(e) for e in EXTS if sc.with_suffix(e).exists()), None)
        if doc is None:
            print(f"- {sc.stem}: no document file yet (run with --download or add {sc.stem}.pdf)")
            continue
        await ingest(doc, meta, extract=not args.no_extract)
    print(f"registry: {settings.data_dir / 'registry.json'}")


if __name__ == "__main__":
    asyncio.run(main())
