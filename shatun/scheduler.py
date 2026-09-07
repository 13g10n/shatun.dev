"""Assign queued work to idle named agents within a project."""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from shatun.events import EventBus
from shatun.models import AGENT_IDLE, AGENT_RUNNING, TASK_QUEUED
from shatun.runner import Runner
from shatun.serialize import has_label
from shatun.store import Store

log = logging.getLogger("shatun.scheduler")


class Scheduler:
    def __init__(self, store: Store, bus: EventBus, runner: Runner) -> None:
        self.store = store
        self.bus = bus
        self.runner = runner
        self._tasks: set[asyncio.Task] = set()

    async def enqueue_issue(self, project_id: UUID, number: int) -> UUID:
        project = await self.store.get_project(project_id)
        if project is None:
            raise KeyError("project not found")
        issue = await self.store.get_issue_by_number(project_id, number)
        if issue is None:
            raise KeyError(f"issue #{number} is not in the database")
        if issue.state != "open" or not has_label(issue.labels_json, project.label):
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
                try:
                    settings = await self.store.get_settings()
                    timeout = max(1, int(settings.scheduler_seconds or 5))
                except Exception:
                    timeout = 5
                waiter = asyncio.create_task(pubsub.get_message(ignore_subscribe_messages=True, timeout=timeout))
                stopper = asyncio.create_task(stop.wait())
                done, pending = await asyncio.wait({waiter, stopper}, return_when=asyncio.FIRST_COMPLETED)
                for task in pending:
                    task.cancel()
        finally:
            await pubsub.unsubscribe()
            await pubsub.aclose()

    async def _tick(self) -> None:
        while True:
            assigned = False
            for agent in await self.store.idle_agents():
                queued = await self.store.oldest_queued(agent.project_id)
                if queued is None:
                    project = await self.store.get_project(agent.project_id)
                    if project is None:
                        continue
                    issue = await self.store.oldest_eligible_issue(project)
                    if issue is None:
                        continue
                    queued = await self.store.insert_run(issue.id, TASK_QUEUED)
                if queued.agent_id and queued.status == "running":
                    continue
                await self.store.update_run(queued.id, agent_id=agent.id, status="running")
                await self.store.set_agent_status(agent.id, AGENT_RUNNING, queued.id)
                log.info("starting run %s on agent %s", queued.id, agent.name)
                task = asyncio.create_task(self.runner.execute(queued.id, agent.id), name=f"run-{queued.id}")
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)
                assigned = True
                break
            if not assigned:
                return
