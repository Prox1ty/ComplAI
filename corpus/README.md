# Seed corpus

Each document is a PDF (or `.txt` / `.md`) plus a sidecar `.json` with the same stem:

```json
{ "jurisdiction": "global", "title": "...", "issuer": "...", "url": "...", "topics": ["..."],
  "download_url": "optional direct PDF link", "effective_date": "optional YYYY-MM-DD" }
```

`python scripts/seed_corpus.py --download` fetches any missing PDF from `download_url`, then ingests
everything into the registry, Chroma and SQLite and extracts obligations (needs an LLM key).
If a download link has moved, save the PDF here manually under the sidecar's stem
(for example `fatf-recommendations.pdf`). PDFs are git-ignored.

`topics` must use ids from `backend/taxonomy.py`. Jurisdiction keys follow the registry format:
`global`, `EU`, `GCC`, `PK`, `PK/Punjab`, `US/NY`.
