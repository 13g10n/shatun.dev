"""In-process handles for live agent processes."""

from __future__ import annotations

import asyncio
import os
import signal
from dataclasses import dataclass, field
from uuid import UUID


@dataclass
class LiveRun:
    agent_id: UUID
    run_id: UUID
    proc: asyncio.subprocess.Process | None = None
    stop: asyncio.Event = field(default_factory=asyncio.Event)


class Runtime:
    def __init__(self) -> None:
        self.live: dict[UUID, LiveRun] = {}

    def get(self, agent_id: UUID) -> LiveRun | None:
        return self.live.get(agent_id)

    def find_run(self, run_id: UUID) -> LiveRun | None:
        for item in self.live.values():
            if item.run_id == run_id:
                return item
        return None

    def attach(self, agent_id: UUID, run_id: UUID, proc: asyncio.subprocess.Process) -> LiveRun:
        live = LiveRun(agent_id=agent_id, run_id=run_id, proc=proc)
        self.live[agent_id] = live
        return live

    def claim(self, agent_id: UUID, run_id: UUID) -> LiveRun:
        live = LiveRun(agent_id=agent_id, run_id=run_id)
        self.live[agent_id] = live
        return live

    def clear(self, agent_id: UUID) -> None:
        self.live.pop(agent_id, None)


async def kill_proc(proc: asyncio.subprocess.Process | None, grace: float = 20) -> int | None:
    if proc is None or proc.returncode is not None:
        return proc.returncode if proc else None
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        proc.terminate()
    try:
        await asyncio.wait_for(proc.wait(), timeout=grace)
    except TimeoutError:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            proc.kill()
        await proc.wait()
    return proc.returncode
