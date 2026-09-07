"""Database helpers used by workers (own sessions)."""

from __future__ import annotations

import json
import logging
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from shatun.events import EventBus
from shatun.models import (
    AGENT_IDLE,
    AGENT_RUNNING,
    PHASE_QUEUED,
    TASK_FAILED,
    TASK_QUEUED,
    TASK_RUNNING,
    Agent,
    Issue,
    Message,
    Run,
)
from shatun.serialize import agent_view, has_label, issue_view, message_view, run_view

log = logging.getLogger("shatun.store")
PR_LINE = re.compile(r"^PR:\s*(\S+)", re.MULTILINE)
PR_URL = re.compile(r"https://github\.com/[^/\s]+/[^/\s]+/pull/\d+")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Store:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], bus: EventBus, log_root: Path) -> None:
        self.sessions = sessions
        self.bus = bus
        self.log_root = log_root

    async def seed_agent(self, name: str) -> Agent:
        async with self.sessions() as session:
            existing = (await session.execute(select(Agent).where(Agent.name == name))).scalar_one_or_none()
            if existing:
                if not getattr(existing, "avatar_seed", ""):
                    existing.avatar_seed = secrets.token_hex(8)
                    await session.commit()
                    await session.refresh(existing)
                return existing
            agent = Agent(name=name, status=AGENT_IDLE, avatar_seed=secrets.token_hex(8))
            session.add(agent)
            await session.commit()
            await session.refresh(agent)
            await self.bus.publish("agent.created", agent_view(agent), wake=True)
            return agent

    async def list_agents(self) -> list[Agent]:
        async with self.sessions() as session:
            return list((await session.execute(select(Agent).order_by(Agent.created_at))).scalars())

    async def get_agent(self, agent_id: UUID) -> Agent | None:
        async with self.sessions() as session:
            return await session.get(Agent, agent_id)

    async def add_agent(
        self,
        name: str,
        *,
        persona: str = "",
        instructions: str = "",
        mcp_servers: list | None = None,
        paused: bool = False,
        avatar_seed: str | None = None,
    ) -> Agent:
        async with self.sessions() as session:
            agent = Agent(
                name=name.strip(),
                status=AGENT_IDLE,
                persona=persona or "",
                instructions=instructions or "",
                mcp_servers=list(mcp_servers or []),
                paused=bool(paused),
                avatar_seed=avatar_seed or secrets.token_hex(8),
            )
            session.add(agent)
            try:
                await session.commit()
            except Exception as exc:
                await session.rollback()
                raise ValueError(f"could not add agent {name!r}") from exc
            await session.refresh(agent)
            await self.bus.publish("agent.created", agent_view(agent), wake=True)
            return agent

    async def delete_agent(self, agent_id: UUID) -> None:
        async with self.sessions() as session:
            agent = await session.get(Agent, agent_id)
            if agent is None:
                raise KeyError("agent not found")
            if agent.status == AGENT_RUNNING:
                raise ValueError("cannot remove a running agent")
            await session.delete(agent)
            await session.commit()
        await self.bus.publish("agent.deleted", {"id": str(agent_id)}, wake=True)

    async def update_agent(self, agent_id: UUID, **fields: Any) -> Agent:
        allowed = {"name", "persona", "instructions", "mcp_servers", "paused", "avatar_seed"}
        async with self.sessions() as session:
            agent = await session.get(Agent, agent_id)
            if agent is None:
                raise KeyError("agent not found")
            for key, value in fields.items():
                if key not in allowed:
                    continue
                if key == "name" and isinstance(value, str):
                    value = value.strip()
                    if not value:
                        raise ValueError("name is required")
                setattr(agent, key, value)
            await session.commit()
            await session.refresh(agent)
            await self.bus.publish("agent.updated", agent_view(agent), wake=True)
            return agent

    async def set_agent_status(self, agent_id: UUID, status: str, current_run_id: UUID | None = None) -> None:
        async with self.sessions() as session:
            agent = await session.get(Agent, agent_id)
            if agent is None:
                return
            agent.status = status
            agent.current_run_id = current_run_id
            await session.commit()
            await session.refresh(agent)
            await self.bus.publish("agent.updated", agent_view(agent))

    async def upsert_issue(self, repo: str, item: dict[str, Any]) -> Issue:
        number = int(item["number"])
        async with self.sessions() as session:
            issue = (
                await session.execute(select(Issue).where(Issue.repo == repo, Issue.number == number))
            ).scalar_one_or_none()
            if issue is None:
                issue = Issue(repo=repo, number=number)
                session.add(issue)
            issue.title = str(item.get("title") or "")
            issue.body = str(item.get("body") or "")
            issue.html_url = str(item.get("url") or "")
            issue.labels_json = item.get("labels") or []
            issue.state = str(item.get("state") or "open").lower()
            issue.github_updated_at = str(item.get("updatedAt") or "")
            await session.commit()
            await session.refresh(issue)
            await self.bus.publish("issue.updated", {"id": str(issue.id), "number": issue.number})
            return issue

    async def mark_missing_closed(self, repo: str, seen: list[int]) -> None:
        async with self.sessions() as session:
            q = select(Issue).where(Issue.repo == repo, Issue.state == "open")
            if seen:
                q = q.where(Issue.number.not_in(seen))
            rows = list((await session.execute(q)).scalars())
            for issue in rows:
                issue.state = "closed"
            await session.commit()

    async def list_issues(self, repo: str) -> list[Issue]:
        async with self.sessions() as session:
            return list(
                (await session.execute(select(Issue).where(Issue.repo == repo).order_by(Issue.number.desc()))).scalars()
            )

    async def get_issue_by_number(self, repo: str, number: int) -> Issue | None:
        async with self.sessions() as session:
            return (
                await session.execute(select(Issue).where(Issue.repo == repo, Issue.number == number))
            ).scalar_one_or_none()

    def _active_run_query(self, issue_id: UUID) -> Select[tuple[Run]]:
        return select(Run).where(Run.issue_id == issue_id, Run.status.in_((TASK_QUEUED, TASK_RUNNING)))

    async def active_run_for_issue(self, issue_id: UUID) -> Run | None:
        async with self.sessions() as session:
            return (await session.execute(self._active_run_query(issue_id))).scalar_one_or_none()

    async def oldest_queued(self) -> Run | None:
        async with self.sessions() as session:
            return (
                await session.execute(
                    select(Run)
                    .options(selectinload(Run.issue), selectinload(Run.agent))
                    .where(Run.status == TASK_QUEUED)
                    .order_by(Run.created_at.asc())
                    .limit(1)
                )
            ).scalar_one_or_none()

    async def oldest_eligible_issue(self, repo: str, label: str) -> Issue | None:
        async with self.sessions() as session:
            issues = list(
                (
                    await session.execute(
                        select(Issue).where(Issue.repo == repo, Issue.state == "open").order_by(Issue.github_updated_at.asc())
                    )
                ).scalars()
            )
            for issue in issues:
                if not has_label(issue.labels_json, label):
                    continue
                existing = (
                    await session.execute(select(Run.id).where(Run.issue_id == issue.id).limit(1))
                ).first()
                if existing is None:
                    return issue
            return None

    async def idle_agents(self) -> list[Agent]:
        async with self.sessions() as session:
            return list(
                (
                    await session.execute(
                        select(Agent)
                        .where(Agent.status == AGENT_IDLE, Agent.paused.is_(False))
                        .order_by(Agent.created_at)
                    )
                ).scalars()
            )

    async def insert_run(self, issue_id: UUID, status: str = TASK_QUEUED) -> Run:
        async with self.sessions() as session:
            run = Run(issue_id=issue_id, status=status, phase=PHASE_QUEUED)
            session.add(run)
            await session.commit()
            run = (
                await session.execute(
                    select(Run).options(selectinload(Run.issue), selectinload(Run.agent)).where(Run.id == run.id)
                )
            ).scalar_one()
            await self.bus.publish("run.updated", run_view(run), wake=True)
            return run

    async def get_run(self, run_id: UUID) -> Run | None:
        async with self.sessions() as session:
            return (
                await session.execute(
                    select(Run).options(selectinload(Run.issue), selectinload(Run.agent)).where(Run.id == run_id)
                )
            ).scalar_one_or_none()

    async def list_runs(self, limit: int = 50) -> list[Run]:
        async with self.sessions() as session:
            return list(
                (
                    await session.execute(
                        select(Run)
                        .options(selectinload(Run.issue), selectinload(Run.agent))
                        .order_by(Run.created_at.desc())
                        .limit(limit)
                    )
                ).scalars()
            )

    async def list_messages(self, run_id: UUID) -> list[Message]:
        async with self.sessions() as session:
            return list(
                (
                    await session.execute(
                        select(Message).where(Message.run_id == run_id).order_by(Message.created_at.asc())
                    )
                ).scalars()
            )

    async def update_run(self, run_id: UUID, **fields: Any) -> Run | None:
        async with self.sessions() as session:
            run = (
                await session.execute(
                    select(Run).options(selectinload(Run.issue), selectinload(Run.agent)).where(Run.id == run_id)
                )
            ).scalar_one_or_none()
            if run is None:
                return None
            for key, value in fields.items():
                setattr(run, key, value)
            await session.commit()
            await session.refresh(run)
            await session.refresh(run, attribute_names=["issue", "agent"])
            await self.bus.publish("run.updated", run_view(run))
            return run

    async def recover_stale(self) -> None:
        async with self.sessions() as session:
            running = list((await session.execute(select(Run).where(Run.status == TASK_RUNNING))).scalars())
            now = utcnow()
            for run in running:
                run.status = TASK_FAILED
                run.finished_at = now
                run.last_error = "orchestrator restarted"
                run.phase = "done"
            agents = list((await session.execute(select(Agent).where(Agent.status == AGENT_RUNNING))).scalars())
            for agent in agents:
                agent.status = AGENT_IDLE
                agent.current_run_id = None
            await session.commit()

    async def add_message(self, run_id: UUID, event: dict[str, Any]) -> Message:
        kind = str(event.get("kind") or "session")
        text = str(event.get("text") or "")
        async with self.sessions() as session:
            last = (
                await session.execute(
                    select(Message).where(Message.run_id == run_id).order_by(Message.created_at.desc()).limit(1)
                )
            ).scalar_one_or_none()
            if last is not None and kind in {"message", "thought"} and last.kind == kind:
                last.text = (last.text or "") + text
                last.payload = event.get("payload") or last.payload
                await session.commit()
                await session.refresh(last)
                message = last
            else:
                message = Message(
                    run_id=run_id,
                    kind=kind,
                    tool_call_id=event.get("tool_call_id"),
                    title=event.get("title"),
                    status=event.get("status"),
                    text=text,
                    payload=event.get("payload") or {},
                )
                session.add(message)
                await session.commit()
                await session.refresh(message)
        self._append_jsonl(run_id, event)
        view = message_view(message)
        await self.bus.publish("run.message", view)
        return message

    def _append_jsonl(self, run_id: UUID, event: dict[str, Any]) -> None:
        path = self.log_root / f"{run_id}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps({"ts": utcnow().isoformat(), **event}, default=str)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    def parse_pr_url(self, run_id: UUID) -> str | None:
        path = self.log_root / f"{run_id}.jsonl"
        if not path.is_file():
            return None
        text = path.read_text(encoding="utf-8", errors="replace")
        match = PR_LINE.search(text)
        if match and match.group(1).lower() != "none":
            return match.group(1)
        match = PR_URL.search(text)
        return match.group(0) if match else None
