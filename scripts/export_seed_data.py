"""Export the regulation knowledge base into deploy/seed-data/ for the Docker image.

Copies what is expensive to rebuild (downloaded regulations, their chunks and
embeddings, and the LLM-extracted obligations) and leaves out everything
per-run (uploaded policies, run results, caches):

    deploy/seed-data/registry.json   jurisdiction -> document ids
    deploy/seed-data/docs.sqlite     document metadata + cached obligations
    deploy/seed-data/vectors.sqlite  regulatory_facts chunks with embeddings only

The container copies these into its data directory on first start, so a fresh
deployment needs no web search and no token-consuming re-extraction. The
sqlite-vec index is rebuilt from the stored embeddings at startup.

    python scripts/export_seed_data.py              # from ./data (or DATA_DIR)
    python scripts/export_seed_data.py --src D:\\complai-data
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FACTS = "regulatory_facts"


def export(src: Path, dst: Path) -> dict:
    for name in ("registry.json", "docs.sqlite", "vectors.sqlite"):
        if not (src / name).exists():
            raise SystemExit(f"{src / name} not found. Run an analysis (or scripts/seed_corpus.py) first.")
    dst.mkdir(parents=True, exist_ok=True)

    shutil.copyfile(src / "registry.json", dst / "registry.json")

    # docs.sqlite: use the backup API so a live WAL database is copied consistently
    out_docs = dst / "docs.sqlite"
    out_docs.unlink(missing_ok=True)
    with sqlite3.connect(src / "docs.sqlite") as s, sqlite3.connect(out_docs) as d:
        s.backup(d)
    with sqlite3.connect(out_docs) as d:
        docs = d.execute("SELECT COUNT(*), SUM(obligations_json IS NOT NULL) FROM docs").fetchone()
        d.execute("PRAGMA journal_mode=DELETE")

    # vectors.sqlite: only the regulatory chunks, plain table (no extension needed to read it)
    out_vec = dst / "vectors.sqlite"
    out_vec.unlink(missing_ok=True)
    with sqlite3.connect(src / "vectors.sqlite") as s, sqlite3.connect(out_vec) as d:
        d.execute(
            "CREATE TABLE vectors (collection TEXT NOT NULL, id TEXT NOT NULL, doc TEXT NOT NULL,"
            " meta TEXT NOT NULL, emb BLOB NOT NULL, PRIMARY KEY (collection, id))"
        )
        rows = s.execute(
            "SELECT collection, id, doc, meta, emb FROM vectors WHERE collection = ? ORDER BY id", (FACTS,)
        ).fetchall()
        d.executemany("INSERT INTO vectors VALUES (?,?,?,?,?)", rows)
        d.commit()
        dims = {len(r[4]) // 4 for r in rows}
    with sqlite3.connect(out_vec) as d:
        d.execute("VACUUM")

    reg = json.loads((dst / "registry.json").read_text(encoding="utf-8"))
    summary = {
        "documents": docs[0], "documents_with_obligations": docs[1] or 0, "chunks": len(rows),
        "embedding_dims": sorted(dims), "jurisdictions": sorted(reg),
    }
    (dst / "manifest.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    from backend.config import settings

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", type=Path, default=settings.data_dir, help="data directory to export from")
    ap.add_argument("--dst", type=Path, default=ROOT / "deploy" / "seed-data")
    args = ap.parse_args()
    summary = export(args.src, args.dst)
    print(json.dumps(summary, indent=2))
    if len(summary["embedding_dims"]) != 1:
        print("warning: mixed embedding sizes; re-index with a single EMBED_MODEL before deploying")
    print(f"wrote {args.dst}")


if __name__ == "__main__":
    main()
