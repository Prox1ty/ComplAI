"""Per-run progress events. Events are kept in a history list so a client that
connects late (or reconnects) replays everything, then waits for new ones."""
from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator

from backend.schemas import ProgressEvent

TERMINAL = {"done", "error"}


class _Channel:
    def __init__(self) -> None:
        self.events: list[ProgressEvent] = []
        self.cond = asyncio.Condition()

    @property
    def finished(self) -> bool:
        return bool(self.events) and self.events[-1].phase in TERMINAL


_channels: dict[str, _Channel] = {}


def channel(run_id: str) -> _Channel:
    ch = _channels.get(run_id)
    if ch is None:
        ch = _channels[run_id] = _Channel()
    return ch


async def emit(run_id: str, phase: str, status: str = "progress", detail: str = "", progress: float = 0.0) -> None:
    ch = channel(run_id)
    ev = ProgressEvent(phase=phase, status=status, detail=detail, progress=round(max(0.0, min(1.0, progress)), 3))
    async with ch.cond:
        ch.events.append(ev)
        ch.cond.notify_all()


def history(run_id: str) -> list[ProgressEvent]:
    return list(channel(run_id).events)


async def subscribe(run_id: str, keepalive: float = 15.0) -> AsyncIterator[str]:
    """Yield SSE-formatted frames until the run reaches a terminal phase."""
    ch = channel(run_id)
    i = 0
    while True:
        timed_out = False
        async with ch.cond:
            if i >= len(ch.events):
                try:
                    await asyncio.wait_for(ch.cond.wait(), timeout=keepalive)
                except asyncio.TimeoutError:
                    timed_out = True
            pending = ch.events[i:]
            i = len(ch.events)
        if timed_out and not pending:
            yield ": keepalive\n\n"
            continue
        for ev in pending:
            yield f"data: {json.dumps(ev.model_dump())}\n\n"
            if ev.phase in TERMINAL:
                return


def drop(run_id: str) -> None:
    _channels.pop(run_id, None)
