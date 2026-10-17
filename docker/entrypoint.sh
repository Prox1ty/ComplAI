#!/bin/sh
# Seed the data directory on first start, then run the API (which also serves the frontend).
set -e

DATA_DIR="${DATA_DIR:-/data}"
mkdir -p "$DATA_DIR/runs"

if [ ! -f "$DATA_DIR/registry.json" ] && [ -d /app/seed-data ]; then
  echo "Seeding $DATA_DIR from the bundled regulation knowledge base"
  for f in registry.json docs.sqlite vectors.sqlite; do
    [ -f "/app/seed-data/$f" ] && cp "/app/seed-data/$f" "$DATA_DIR/$f"
  done
fi

if [ -z "$GROQ_API_KEY" ] && [ -z "$OPENAI_API_KEY" ] && [ -z "$ANTHROPIC_API_KEY" ]; then
  echo "WARNING: no LLM API key set (GROQ_API_KEY). The UI will load, but analyses will fail until it is set."
fi

exec uvicorn backend.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips="*"
