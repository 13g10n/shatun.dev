"""Assign queued work to idle named agents."""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from shatun.config import Config
from shatun.events import EventBus
from shatun.models import AGENT_IDLE, AGENT_RUNNING, TASK_QUEUED
from shatun.runner import Runner
from shatun.store import Store

log = logging.getLogger("shatun.scheduler")


class Scheduler:
    def __init__(self, cfg: Config, store: Store, bus: EventBus, runner: Runner) -> None:
        self.cfg = cfg
        self.store = store
        self.bus = bus
        self.runner = runner
        self._tasks: set[asyncio.Task] = set()

    async def enqueue_issue(self, number: int) -> UUID:
        issue = await self.store.get_issue_by_number(self.cfg.repo, number)
        if issue is None:
            raise KeyError(f"issue #{number} is not in the database")
        from shatun.serialize import has_label

        if issue.state != "open" or not has_label(issue.labels_json, self.cfg.label):
            raise ValueError(f"issue #{number} is not eligible")
        if await self.store.active_run_for_issue(issue.id):
            raise ValueError(f"issue #{number} already has an active run")
        try:
            run = await self.store.insert_run(issue.id, TASK_QUEUED)
        except IntegrityError as exc:
            raise ValueError(f"issue #{number} already has an active run") from exc
        return run.id

    async def requeue(self, run_id: UUID) -> UUID:
        run = await self.store.get_run(run_id)
        if run is None:
            raise KeyError("run not found")
        if run.status not in ("failed", "stopped"):
            raise ValueError("requeue only from failed/stopped")
        if await self.store.active_run_for_issue(run.issue_id):
            raise ValueError("issue already has an active run")
        new_run = await self.store.insert_run(run.issue_id, TASK_QUEUED)
        return new_run.id

    async def loop(self, stop: asyncio.Event) -> None:
        pubsub = await self.bus.subscribe_wake()
        try:
            while not stop.is_set():
                try:
                    await self._tick()
                except Exception:
                    log.exception("scheduler tick failed")
                waiter = asyncio.create_task(pubsub.get_message(ignore_subscribe_messages=True, timeout=self.cfg.scheduler_seconds))
                stopper = asyncio.create_task(stop.wait())
                done, pending = await asyncio.wait({waiter, stopper}, return_when=asyncio.FIRST_COMPLETED)
                for task in pending:
                    task.cancel()
        finally:
            await pubsub.unsubscribe()
            await pubsub.aclose()

    async def _tick(self) -> None:
        while True:
            idle = await self.store.idle_agents()
            if not idle:
                return
            agent = idle[0]
            queued = await self.store.oldest_queued()
            if queued is None:
                issue = await self.store.oldest_eligible_issue(self.cfg.repo, self.cfg.label)
                if issue is None:
                    return
                queued = await self.store.insert_run(issue.id, TASK_QUEUED)
            if queued.agent_id and queued.status == "running":
                return
            await self.store.update_run(queued.id, agent_id=agent.id, status="running")
            await self.store.set_agent_status(agent.id, AGENT_RUNNING, queued.id)
            log.info("starting run %s on agent %s", queued.id, agent.name)
            task = asyncio.create_task(self.runner.execute(queued.id, agent.id), name=f"run-{queued.id}")
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
