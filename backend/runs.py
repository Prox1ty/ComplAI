"""Run state: in memory plus JSON files under ``data/runs/{run_id}/`` so a
finished report survives a page refresh or a server restart."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.config import settings
from backend.schemas import Result


class RunStore:
    def __init__(self) -> None:
        self.state: dict[str, dict[str, Any]] = {}
        self.results: dict[str, Result] = {}

    def dir(self, run_id: str) -> Path:
        p = settings.runs_dir / run_id
        p.mkdir(parents=True, exist_ok=True)
        return p

    def create(self, run_id: str, info: dict[str, Any]) -> None:
        st = {"run_id": run_id, "status": "running", "created_at": datetime.now(timezone.utc).isoformat(), **info}
        self.state[run_id] = st
        self._write(run_id, "state.json", st)

    def update(self, run_id: str, **fields: Any) -> None:
        st = self.get_state(run_id) or {"run_id": run_id}
        st.update(fields)
        self.state[run_id] = st
        self._write(run_id, "state.json", st)

    def get_state(self, run_id: str) -> dict[str, Any] | None:
        if run_id in self.state:
            return self.state[run_id]
        p = settings.runs_dir / run_id / "state.json"
        if p.exists():
            self.state[run_id] = json.loads(p.read_text(encoding="utf-8"))
            return self.state[run_id]
        return None

    def save_result(self, result: Result, debug: dict[str, Any] | None = None) -> None:
        self.results[result.run_id] = result
        self._write(result.run_id, "result.json", result.model_dump())
        if debug is not None:
            self._write(result.run_id, "debug.json", debug)
        self.update(result.run_id, status="done")

    def get_result(self, run_id: str) -> Result | None:
        if run_id in self.results:
            return self.results[run_id]
        p = settings.runs_dir / run_id / "result.json"
        if p.exists():
            r = Result.model_validate_json(p.read_text(encoding="utf-8"))
            self.results[run_id] = r
            return r
        return None

    def _write(self, run_id: str, name: str, data: Any) -> None:
        path = self.dir(run_id) / name
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        tmp.replace(path)


store = RunStore()
