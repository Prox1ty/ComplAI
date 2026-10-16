"""Jurisdiction resolution, ``registry.json`` (jurisdiction -> doc ids) and the
SQLite ``docs`` table holding document metadata and cached obligations."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from backend.config import settings
from backend.schemas import DocMeta

EU = "AT BE BG HR CY CZ DK EE FI FR DE GR HU IE IT LV LT LU MT NL PL PT RO SK SI ES SE".split()
GCC = "AE BH KW OM QA SA".split()
EEA_EXTRA = "IS LI NO".split()
BLOCS: dict[str, list[str]] = {}
for _c in EU:
    BLOCS.setdefault(_c, []).append("EU")
for _c in EEA_EXTRA:
    BLOCS.setdefault(_c, []).append("EEA")
for _c in GCC:
    BLOCS.setdefault(_c, []).append("GCC")

_lock = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS docs (
  doc_id TEXT PRIMARY KEY,
  title TEXT, issuer TEXT, url TEXT, jurisdiction TEXT, topics TEXT, language TEXT,
  effective_date TEXT, fetched_at TEXT, content_hash TEXT, obligations_json TEXT
);
CREATE INDEX IF NOT EXISTS docs_hash ON docs(content_hash);
CREATE INDEX IF NOT EXISTS docs_url ON docs(url);
"""


def _clean(s: str | None) -> str:
    return " ".join((s or "").replace("/", " ").split())


def resolve_jurisdictions(country: str, region: str | None = None, city: str | None = None) -> list[str]:
    """Most specific -> broadest, e.g. ``['PK/Punjab', 'PK', 'global']`` (+ blocs before global)."""
    c = (country or "").strip().upper()
    if not c:
        return ["global"]
    r, ci = _clean(region), _clean(city)
    chain: list[str] = []
    if r and ci:
        chain.append(f"{c}/{r}/{ci}")
    if r:
        chain.append(f"{c}/{r}")
    chain.append(c)
    chain.extend(BLOCS.get(c, []))
    chain.append("global")
    return chain


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    query = [(k, v) for k, v in parse_qsl(parts.query) if not k.lower().startswith(("utm_", "fbclid", "gclid"))]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower() or "https", parts.netloc.lower(), path, urlencode(sorted(query)), ""))


def doc_id_for_url(url: str) -> str:
    return hashlib.sha1(normalize_url(url).encode("utf-8")).hexdigest()


def doc_id_for_bytes(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def content_hash(text: str) -> str:
    return hashlib.sha1(" ".join(text.split()).encode("utf-8")).hexdigest()


class Registry:
    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = Path(data_dir or settings.data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.json_path = self.data_dir / "registry.json"
        self.db_path = self.data_dir / "docs.sqlite"
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    # registry.json ---------------------------------------------------------
    def _load(self) -> dict[str, list[str]]:
        if not self.json_path.exists():
            return {}
        try:
            return json.loads(self.json_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def _save(self, reg: dict[str, list[str]]) -> None:
        tmp = self.json_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(reg, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.json_path)

    def doc_ids_for(self, chain: list[str]) -> list[str]:
        reg = self._load()
        out: list[str] = []
        for key in chain:
            for d in reg.get(key, []):
                if d not in out:
                    out.append(d)
        return out

    # docs table -------------------------------------------------------------
    def add_doc(self, meta: DocMeta) -> None:
        with _lock:
            row = meta.model_dump()
            row["topics"] = json.dumps(meta.topics)
            row["fetched_at"] = row["fetched_at"] or datetime.now(timezone.utc).isoformat(timespec="seconds")
            existing = self.get_doc(meta.doc_id)
            if existing and existing.obligations_json and not row.get("obligations_json"):
                row["obligations_json"] = existing.obligations_json
            cols = ",".join(row)
            self._conn.execute(
                f"INSERT OR REPLACE INTO docs ({cols}) VALUES ({','.join('?' * len(row))})", list(row.values())
            )
            self._conn.commit()
            reg = self._load()
            ids = reg.setdefault(meta.jurisdiction, [])
            if meta.doc_id not in ids:
                ids.append(meta.doc_id)
            self._save(reg)

    def _row(self, r: sqlite3.Row | None) -> DocMeta | None:
        if r is None:
            return None
        d = dict(r)
        try:
            d["topics"] = json.loads(d.get("topics") or "[]")
        except json.JSONDecodeError:
            d["topics"] = []
        return DocMeta(**d)

    def get_doc(self, doc_id: str) -> DocMeta | None:
        with _lock:
            return self._row(self._conn.execute("SELECT * FROM docs WHERE doc_id=?", (doc_id,)).fetchone())

    def find_by_hash(self, h: str) -> DocMeta | None:
        with _lock:
            return self._row(self._conn.execute("SELECT * FROM docs WHERE content_hash=? LIMIT 1", (h,)).fetchone())

    def find_by_url(self, url: str) -> DocMeta | None:
        return self.get_doc(doc_id_for_url(url))

    def get_docs(self, chain: list[str], topics: list[str] | None = None) -> list[DocMeta]:
        docs = [d for d in (self.get_doc(i) for i in self.doc_ids_for(chain)) if d]
        if topics:
            want = set(topics)
            docs = [d for d in docs if set(d.topics) & want]
        return docs

    def topic_coverage(self, chain: list[str], topics: list[str]) -> dict[str, int]:
        docs = self.get_docs(chain)
        return {t: sum(1 for d in docs if t in d.topics) for t in topics}

    def set_obligations(self, doc_id: str, obligations_json: str) -> None:
        with _lock:
            self._conn.execute("UPDATE docs SET obligations_json=? WHERE doc_id=?", (obligations_json, doc_id))
            self._conn.commit()

    def all_docs(self) -> list[DocMeta]:
        with _lock:
            return [self._row(r) for r in self._conn.execute("SELECT * FROM docs").fetchall()]  # type: ignore[misc]

    def close(self) -> None:
        self._conn.close()


_registry: Registry | None = None


def get_registry() -> Registry:
    global _registry
    with _lock:
        if _registry is None:
            _registry = Registry()
        return _registry


def reset_registry() -> None:
    global _registry
    with _lock:
        if _registry is not None:
            _registry.close()
        _registry = None


def get_docs(chain: list[str], topics: list[str] | None = None) -> list[DocMeta]:
    return get_registry().get_docs(chain, topics)


def add_doc(meta: DocMeta) -> None:
    get_registry().add_doc(meta)
