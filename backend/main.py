"""FastAPI app: upload a policy, stream progress over SSE, fetch the report."""
from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse

from backend.config import ROOT, settings
from backend.orchestrator import Orchestrator, run_fake
from backend.runs import store
from backend.schemas import Result, RunInputs
from backend.taxonomy import POLICY_TYPE_TOPICS
from backend.tools import sse
from backend.tools.parse import SUPPORTED

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
settings.ensure_dirs()

app = FastAPI(title="ComplAI", version="0.1.0")
app.add_middleware(
    CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"], allow_credentials=False,
)
_tasks: set[asyncio.Task] = set()
INSTITUTIONS = {"Commercial bank", "Digital bank", "Credit union", "Microfinance", "Other"}


@app.get("/api/health")
async def health() -> dict:
    from backend.tools.vectorstore import index_info

    return {
        "status": "ok",
        "fake_pipeline": settings.fake_pipeline,
        "provider": settings.llm_provider,
        "vector_search": index_info(),
        "vector_backend_setting": settings.vector_backend,
        "data_dir": str(settings.data_dir.resolve()),
    }


@app.post("/api/runs")
async def create_run(
    file: UploadFile = File(...),
    country: str = Form(...),
    region: str = Form(""),
    city: str = Form(""),
    timezone: str = Form("UTC"),
    policy_type: str = Form(...),
    institution_type: str = Form(...),
) -> dict:
    name = Path(file.filename or "policy.txt").name
    ext = Path(name).suffix.lower()
    if ext not in SUPPORTED:
        raise HTTPException(415, f"Unsupported file type '{ext or 'unknown'}'. Upload a PDF, DOCX or TXT file.")
    if not country.strip():
        raise HTTPException(422, "Country is required.")
    if policy_type not in POLICY_TYPE_TOPICS:
        raise HTTPException(422, f"Unknown policy type '{policy_type}'.")
    if institution_type not in INSTITUTIONS:
        raise HTTPException(422, f"Unknown institution type '{institution_type}'.")

    run_id = uuid.uuid4().hex[:12]
    dest = store.dir(run_id) / f"upload{ext}"
    limit = settings.max_upload_mb * 1024 * 1024
    size = 0
    with dest.open("wb") as fh:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                fh.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(413, f"File is larger than {settings.max_upload_mb} MB.")
            fh.write(chunk)
    if size == 0:
        dest.unlink(missing_ok=True)
        raise HTTPException(422, "The uploaded file is empty.")

    inputs = RunInputs(
        country=country.strip().upper(), region=region.strip() or None, city=city.strip() or None,
        timezone=timezone.strip() or "UTC", policy_type=policy_type, institution_type=institution_type,
    )
    store.create(run_id, {"filename": name, "inputs": inputs.model_dump()})
    if settings.fake_pipeline:
        coro = run_fake(run_id, inputs, name)
    else:
        coro = Orchestrator(run_id, inputs, dest, name).run()
    task = asyncio.create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return {"run_id": run_id}


@app.get("/api/runs/{run_id}/events")
async def events(run_id: str) -> StreamingResponse:
    state = store.get_state(run_id)
    if state is None:
        raise HTTPException(404, "Unknown run.")
    if not sse.history(run_id):
        # server restarted: replay the terminal state from disk
        if state.get("status") == "done":
            await sse.emit(run_id, "done", "completed", "Report ready", 1.0)
        elif state.get("status") == "error":
            await sse.emit(run_id, "error", "failed", state.get("error", "The analysis failed."), 0.0)
        elif not any(t for t in _tasks if not t.done()):
            await sse.emit(run_id, "error", "failed", "This run was interrupted. Please retry.", 0.0)
    return StreamingResponse(
        sse.subscribe(run_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@app.get("/api/runs/{run_id}/result", response_model=Result)
async def result(run_id: str) -> Result:
    r = store.get_result(run_id)
    if r is None:
        raise HTTPException(404, "Result not ready.")
    return r


# --------------------------------------------------------------------------
# Built frontend (production / Docker): served from the same origin as the API.
# In development Vite serves the frontend and proxies /api, so this is skipped.
# Registered last so every /api route above takes precedence.
# --------------------------------------------------------------------------
import os  # noqa: E402

STATIC_DIR = Path(os.getenv("STATIC_DIR", str(ROOT / "frontend" / "dist"))).resolve()

if (STATIC_DIR / "index.html").is_file():

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str) -> FileResponse:
        if full_path.startswith("api/") or full_path == "api":
            raise HTTPException(404, "Not found.")
        candidate = (STATIC_DIR / full_path).resolve()
        if full_path and candidate.is_file() and STATIC_DIR in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(STATIC_DIR / "index.html")  # single-page app: every other path renders the app
