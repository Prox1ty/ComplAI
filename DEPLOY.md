# Deploying ComplAI on Alternate Futures

ComplAI ships as **one Docker container**: FastAPI serves the API and the built React app from the same URL. Alternate Futures runs container images, so the flow is:

```
your PC ──git push tag──▶ GitHub Actions ──builds──▶ ghcr.io/prox1ty/complai:0.1.0 ──acc──▶ https://<slug>-app.alternatefutures.ai
```

The image contains the regulation knowledge base you already built (`deploy/seed-data/`: 4 Pakistani regulations, 112 sections with embeddings, 192 extracted obligations), so a fresh deployment does not spend tokens re-reading them. Your Groq key is **never** in the image; it is set as an environment variable on the platform.

## 1. Refresh the bundled data (optional)

Only needed if you added regulations since the last export:

```powershell
.\.venv\Scripts\python scripts\export_seed_data.py
git add deploy/seed-data
git commit -m "Refresh seed data"
```

## 2. Build the image (GitHub does it)

```powershell
git push
git tag v0.1.0
git push origin v0.1.0
```

Watch it under **GitHub → Actions → Build and publish Docker image** (about 10 minutes the first time). It publishes `ghcr.io/prox1ty/complai:0.1.0`.

**Make the image public once** (Alternate Futures has no option for private registry logins): GitHub → your profile → **Packages** → `complai` → **Package settings** → **Change visibility** → **Public**. The image holds code and public regulation text only, no secrets.

## 3. Deploy

```powershell
npm install -g @alternatefutures/acc
acc login
acc projects create --name complai
acc regions                     # pick a region and check the price

acc services create --kind docker `
  --image ghcr.io/prox1ty/complai:0.1.0 `
  --port 8000 --name complai `
  --cpu 1 --memory 2Gi --storage 5Gi `
  --region asia -y

acc services env set complai GROQ_API_KEY gsk_your_key_here
acc services deploy             # restart with the key
acc services list               # shows the public URL
acc services logs --tail 100
```

Open the URL. `https://<slug>-app.alternatefutures.ai/api/health` should report `"vector_search": "sqlite-vec v0.1.9"`.

To limit spend during the hackathon, add `--spend budget --budget-total 10` (USD) or `--stop-days 3` to `services create`. `acc services close` stops billing.

## 4. Ship an update

```powershell
git tag v0.1.1
git push origin v0.1.1
acc services deploy --image ghcr.io/prox1ty/complai:0.1.1
```

Always deploy a versioned tag: the platform caches images by tag and refuses `latest`.

## Configuration

Everything in `.env.example` can be set with `acc services env set complai KEY VALUE`. The image already defaults to Groq (`openai/gpt-oss-20b` / `openai/gpt-oss-120b`, 8K TPM, 30 RPM) and sqlite-vec. Common overrides:

| Variable | Why |
| --- | --- |
| `GROQ_API_KEY` | required |
| `TAVILY_API_KEY` | better web search than the DuckDuckGo fallback |
| `LLM_TPM_LIMIT`, `LLM_RPM_LIMIT` | if you upgrade your Groq tier |
| `FAKE_PIPELINE=1` | demo the UI on the bundled mock report without spending tokens |

**Storage.** Runs, caches and newly found regulations are written to `/data`. The Alternate Futures docs do not say whether `--storage` survives a redeploy. If it does not, every new deployment starts again from the bundled seed data, which is fine for a demo: the expensive part is bundled.

## Run the same image locally

```powershell
docker build -t complai .
docker run -p 8000:8000 -e GROQ_API_KEY=gsk_... complai
# open http://localhost:8000
```

## Resource notes

- Image size is roughly 2 GB: CPU-only PyTorch plus the embedding model baked in, so containers start without downloading anything.
- 2 GiB of memory is comfortable for one analysis at a time; use 4Gi if several people will run analyses at once.
- No GPU is needed: the only local model is the small embedding model; the LLM runs on Groq.
