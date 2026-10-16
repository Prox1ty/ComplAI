"""Shared run context handed to every agent."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from backend.llm import current_usage
from backend.schemas import Clause, DocMeta, Inference, PolicyProfile, RunInputs

Emit = Callable[[str, str, str, float], Awaitable[None]]


async def _noop(phase: str, status: str, detail: str, progress: float) -> None:
    return None


@dataclass
class RunContext:
    run_id: str
    inputs: RunInputs
    chain: list[str]
    as_of: str
    clauses: list[Clause] = field(default_factory=list)
    tags: dict[str, Any] = field(default_factory=dict)  # clause_id -> ClauseTag
    profile: PolicyProfile = field(default_factory=PolicyProfile)
    docs: list[DocMeta] = field(default_factory=list)
    inferences: list[Inference] = field(default_factory=list)
    emit: Emit = _noop
    debug: dict[str, list] = field(default_factory=lambda: {"dropped": [], "unverified": [], "errors": [], "skipped": []})

    @property
    def reduced(self) -> bool:
        u = current_usage()
        return bool(u and u.reduced_mode)

    @property
    def substantive(self) -> list[Clause]:
        return [c for c in self.clauses if getattr(self.tags.get(c.id), "substantive", True)]

    def clause(self, cid: str) -> Clause | None:
        return next((c for c in self.clauses if c.id == cid), None)

    def log(self, kind: str, **data: Any) -> None:
        self.debug.setdefault(kind, []).append(data)


def dumps(obj: Any) -> str:
    """Compact JSON for prompts."""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
