# ComplAI — Bank Policy Compliance Agent

A policy officer uploads a draft bank policy and states their jurisdiction. ComplAI finds the regulations that apply, splits the draft into clauses, compares each clause with the regulatory text, and returns a gap report: the draft with red and yellow underlines, hover explanations with cited sources and suggested rewrites, a sortable gap table, and PDF export.

> Decision support for compliance officers, not legal advice. Every finding cites a stored regulatory chunk; findings the verifier cannot support never reach the report.

## Human in the loop

The AI only proposes. In the gap table the reviewer ticks the fixes they accept (or clicks **Apply all fixes**), can **edit any suggested wording** first, and then applies them. ComplAI shows the revised policy with every removal struck through and every addition highlighted, flags fixes it could not apply (for example two fixes rewriting the same clause, so the reviewer can merge them), and exports the **final policy as a Word file**: approved fixes are written straight into the text, with no strikethrough or highlighting. For a Word upload the original document is edited in place, so its formatting is kept. Applying fixes is deterministic code and uses no tokens.

## How it works

```
React SPA  ── POST /api/runs ──▶  Orchestrator (plain Python state machine, no LLM)
           ◀── SSE /events ────    P1 Parse → P2 Search → P3 Index/Context → P4 Analyse → P5 Verify → P6 Suggest
           ◀── GET /result ────
```

| Agent | Model | Job |
| --- | --- | --- |
| PolicyProfiler | small | Tags clauses with taxonomy topics; non-substantive clauses are skipped downstream |
| RegulatorySearch | small (one call) | Registry first; web search only for under-covered topics; fetch, chunk, embed, register |
| ContextAgent | large | 5–12 inferences on risk drivers and supervisory focus (hints, never authority) |
| GapAnalysis | large | Pass A: clause groups vs retrieved chunks. Pass B: stored obligations vs the policy, to find omissions |
| Verifier | small | Deterministic citation checks, then entailment; drops unsupported findings |
| Rewriter | small | Drop-in replacement wording per finding |

Stores: three vector collections that are never mixed (`regulatory_facts`, `context_inferences`, `policy_clauses`) in `data/vectors.sqlite`, indexed with [sqlite-vec](https://github.com/asg017/sqlite-vec) (a `vec0` table partitioned per collection and run; hybrid search fuses its KNN results with BM25), plus `data/registry.json` (jurisdiction key → doc ids), and `data/docs.sqlite` (metadata and cached obligations). Jurisdictions resolve to a chain such as `PK/Punjab → PK → global` (plus `EU`/`GCC` blocs).

All LLM traffic goes through `backend/llm.py:call()`: exact-prompt cache, a TPM/RPM token bucket with a 60-second window guard at 80% of your limits, a concurrency cap of 3, backoff that honours `retry-after`, JSON validation with one repair call, and a per-run token ceiling that switches to reduced mode at 80%.

## Run it

### Frontend only (demo data, no backend)

```bash
cd frontend
npm install
npm run dev:mock        # http://localhost:5173
```

### Full stack

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
cp .env.example .env            # add GROQ_API_KEY (free at console.groq.com), and TAVILY_API_KEY if you have one

# seed the global corpus (FATF Recommendations, Basel Core Principles, Basel AML guidelines)
python scripts/seed_corpus.py --download

uvicorn backend.main:app --reload --port 8000

# second terminal
cd frontend && npm install && npm run dev
```

Never put real keys in `.env.example`: it is committed to git. Only `.env` is ignored.

Set `FAKE_PIPELINE=1` to exercise the real API and SSE stream without any LLM key; the backend replays the mock report.

### Tests

```bash
pytest
```

The suite runs offline: hashing embeddings, an in-memory vector store and a deterministic fake LLM. It covers the clause splitter, quote matcher, chunker, registry, source ranking, hybrid search, the LLM wrapper (repair, retries, caching), a 30-call TPM stress test on a virtual clock, and an end-to-end pipeline run on `samples/sample_aml_policy.txt` (including a fabricated citation the verifier must drop and a repeat run that makes zero web searches).

## Deploy

One Docker image serves the API and the built frontend. See [DEPLOY.md](DEPLOY.md) for Alternate Futures (GitHub Actions builds `ghcr.io/prox1ty/complai`, then `acc services create`). Locally: `docker build -t complai .` then `docker run -p 8000:8000 -e GROQ_API_KEY=... complai`.

## Repository layout

```
frontend/   React + Vite + TS (screens, components, types.ts mirrors backend/schemas.py, mock/result.json)
backend/    main.py, orchestrator.py, llm.py, schemas.py, config.py, taxonomy.py, runs.py, cache.py
  agents/   profiler, search, context, gap, verifier, rewriter, prompts
  tools/    parse, clauses, websearch, fetch, chunk, embed, vectorstore, registry, obligations, quote, sources, sse
  tests/
corpus/     seed document sidecars (.json); PDFs are downloaded or added manually
samples/    sample draft policy
scripts/    seed_corpus.py, build_mock_result.py, export_seed_data.py
deploy/     seed-data/ (regulation knowledge base bundled into the Docker image)
docker/     entrypoint.sh
data/       vectors.sqlite, registry.json, docs.sqlite, runs/{id}/result.json + debug.json
```

`data/runs/{id}/debug.json` lists dropped and unverified findings, skipped sources and every LLM call with its token usage.

## API

- `POST /api/runs` — multipart `file`, `country`, `region`, `city`, `timezone`, `policy_type`, `institution_type` → `{ run_id }`
- `GET /api/runs/{run_id}/events` — SSE `{ phase, status, detail, progress }`; phases `parsing`, `searching`, `analysing`, `verifying`, `suggesting`, `done`, `error`
- `GET /api/runs/{run_id}/result` — the Result JSON (404 until done)
- `POST /api/runs/{run_id}/apply` — body `{ fixes: [{ finding_id, text? }] }`; applies the reviewer's chosen (optionally edited) fixes and returns the revised text, changes and skipped fixes
- `GET /api/runs/{run_id}/revised.docx` / `revised.txt` — downloads of the final revised policy
- `GET /api/health`
