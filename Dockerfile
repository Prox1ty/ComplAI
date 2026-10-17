# ComplAI: one container serving the FastAPI backend and the built React frontend.
#
#   docker build -t complai .
#   docker run -p 8000:8000 -e GROQ_API_KEY=gsk_... complai
#
# API keys are passed at runtime (environment variables), never baked into the image.

# ---- 1. frontend build -------------------------------------------------------
FROM node:20.18-bookworm-slim AS frontend
WORKDIR /fe
COPY frontend/package.json frontend/package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm ci --no-audit --no-fund; else npm install --no-audit --no-fund; fi
COPY frontend/ ./
ENV VITE_USE_MOCK=0 VITE_API_BASE=
RUN npm run build

# ---- 2. python runtime ---------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/app/hf

WORKDIR /app

# CPU-only PyTorch first: the default wheel pulls in several GB of CUDA libraries.
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch

# App dependencies (tests and the optional Chroma backend are not needed at runtime).
COPY backend/requirements.txt /tmp/requirements.txt
RUN grep -vE '^(pytest|pytest-asyncio|chromadb)==' /tmp/requirements.txt > /tmp/req-runtime.txt \
 && pip install -r /tmp/req-runtime.txt

# Bake the embedding model into the image so containers start without downloading it.
ARG EMBED_MODEL=intfloat/multilingual-e5-small
RUN python -c "from sentence_transformers import SentenceTransformer as S; S('${EMBED_MODEL}')"

COPY backend/ /app/backend/
COPY scripts/ /app/scripts/
COPY samples/ /app/samples/
COPY corpus/*.json /app/corpus/
COPY pyproject.toml /app/
COPY deploy/seed-data/ /app/seed-data/
COPY --from=frontend /fe/dist /app/static
COPY docker/entrypoint.sh /app/entrypoint.sh
RUN sed -i 's/\r$//' /app/entrypoint.sh && chmod +x /app/entrypoint.sh \
 && useradd --create-home --uid 10001 app && mkdir -p /data && chown -R app:app /data /app

# Runtime defaults (override with environment variables on the platform).
ENV DATA_DIR=/data \
    STATIC_DIR=/app/static \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    EMBED_BACKEND=st \
    EMBED_MODEL=${EMBED_MODEL} \
    VECTOR_BACKEND=sqlite \
    LLM_PROVIDER=groq \
    SMALL_MODEL=openai/gpt-oss-20b \
    LARGE_MODEL=openai/gpt-oss-120b \
    REASONING_EFFORT=low \
    LLM_TPM_LIMIT=8000 \
    LLM_RPM_LIMIT=30 \
    WEB_SEARCH_ENABLED=1 \
    PORT=8000

USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/api/health', timeout=4)"

ENTRYPOINT ["/app/entrypoint.sh"]
