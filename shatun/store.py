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

from sqlalchemy import Select, delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from shatun.config import DEFAULT_GROK_ARGS, normalize_repo
from shatun.events import EventBus
from shatun.models import (
    AGENT_IDLE,
    AGENT_RUNNING,
    PHASE_QUEUED,
    TASK_FAILED,
    TASK_QUEUED,
    TASK_RUNNING,
    Agent,
    AppSettings,
    Issue,
    Message,
    Project,
    Run,
)
from shatun.serialize import agent_view, has_label, message_view, project_view, run_view, settings_view

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

    async def bootstrap_data(self, legacy: dict[str, Any] | None = None) -> AppSettings:
        settings = await self.ensure_settings(legacy)
        await self._backfill_projects(legacy)
        async with self.sessions() as session:
            await session.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_agents_project_name ON agents (project_id, name)"))
            await session.commit()
        return settings

    async def ensure_settings(self, legacy: dict[str, Any] | None = None) -> AppSettings:
        async with self.sessions() as session:
            row = await session.get(AppSettings, 1)
            if row:
                return row
            src = legacy or {}
            row = AppSettings(
                id=1,
                grok_bin=str(src.get("grok_bin") or "grok"),
                grok_args=list(src.get("grok_args") or list(DEFAULT_GROK_ARGS)),
                xai_api_key=str(src.get("xai_api_key") or ""),
                poll_seconds=int(src.get("poll_seconds") or 60),
                scheduler_seconds=int(src.get("scheduler_seconds") or 5),
                run_timeout_sec=int(src.get("run_timeout_sec") or 2700),
                default_agent_name=str(src.get("default_agent_name") or "Bob"),
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row

    async def get_settings(self) -> AppSettings:
        async with self.sessions() as session:
            row = await session.get(AppSettings, 1)
            if row is None:
                raise RuntimeError("app settings are missing")
            return row

    async def update_settings(self, **fields: Any) -> AppSettings:
        allowed = {
            "grok_bin",
            "grok_args",
            "xai_api_key",
            "poll_seconds",
            "scheduler_seconds",
            "run_timeout_sec",
            "default_agent_name",
        }
        async with self.sessions() as session:
            row = await session.get(AppSettings, 1)
            if row is None:
                raise RuntimeError("app settings are missing")
            for key, value in fields.items():
                if key not in allowed or value is None:
                    continue
                if key == "grok_bin":
                    value = str(value).strip() or "grok"
                elif key == "default_agent_name":
                    value = str(value).strip() or "Bob"
                elif key == "grok_args":
                    value = [str(item) for item in value if str(item).strip()]
                    if not value:
                        value = list(DEFAULT_GROK_ARGS)
                elif key in {"poll_seconds", "scheduler_seconds", "run_timeout_sec"}:
                    value = max(1, int(value))
                elif key == "xai_api_key":
                    value = str(value)
                setattr(row, key, value)
            await session.commit()
            await session.refresh(row)
            await self.bus.publish("settings.updated", settings_view(row), wake=True)
            return row

    async def _backfill_projects(self, legacy: dict[str, Any] | None) -> None:
        async with self.sessions() as session:
            orphan_agents = list((await session.execute(select(Agent).where(Agent.project_id.is_(None)))).scalars())
            orphan_issues = list((await session.execute(select(Issue).where(Issue.project_id.is_(None)))).scalars())
            if not orphan_agents and not orphan_issues:
                return
            repo = ""
            label = "agent"
            if orphan_issues:
                repo = orphan_issues[0].repo
            elif legacy and legacy.get("repo"):
                try:
                    repo = normalize_repo(str(legacy["repo"]))
                except ValueError:
                    repo = ""
            if legacy and legacy.get("label"):
                label = str(legacy["label"])
            if not repo:
                repo = "imported/local"
            existing = (await session.execute(select(Project).where(Project.repo == repo))).scalar_one_or_none()
            if existing is None:
                title = repo.split("/")[-1] or "Imported"
                existing = Project(title=title, repo=repo, label=label)
                session.add(existing)
                await session.flush()
            for agent in orphan_agents:
                agent.project_id = existing.id
            for issue in orphan_issues:
                issue.project_id = existing.id
                if not issue.repo:
                    issue.repo = existing.repo
            await session.commit()

    async def list_projects(self) -> list[Project]:
        async with self.sessions() as session:
            return list((await session.execute(select(Project).order_by(Project.created_at))).scalars())

    async def project_counts(self, project_id: UUID) -> tuple[int, int, int]:
        async with self.sessions() as session:
            agents = (await session.execute(select(func.count(Agent.id)).where(Agent.project_id == project_id))).scalar_one()
            running = (
                await session.execute(
                    select(func.count(Agent.id)).where(Agent.project_id == project_id, Agent.status == AGENT_RUNNING)
                )
            ).scalar_one()
            tasks = (await session.execute(select(func.count(Issue.id)).where(Issue.project_id == project_id))).scalar_one()
            return int(agents), int(running), int(tasks)

    async def get_project(self, project_id: UUID) -> Project | None:
        async with self.sessions() as session:
            return await session.get(Project, project_id)

    async def add_project(self, title: str, repo: str, label: str = "agent") -> Project:
        repo = normalize_repo(repo)
        title = title.strip() or repo.split("/")[-1]
        label = (label or "agent").strip() or "agent"
        async with self.sessions() as session:
            existing = (await session.execute(select(Project).where(Project.repo == repo))).scalar_one_or_none()
            if existing:
                raise ValueError(f"project for {repo} already exists")
            project = Project(title=title, repo=repo, label=label)
            session.add(project)
            try:
                await session.commit()
            except Exception as exc:
                await session.rollback()
                raise ValueError(f"could not create project {repo}") from exc
            await session.refresh(project)
        settings = await self.get_settings()
        await self.seed_agent(project.id, settings.default_agent_name)
        await self.bus.publish("project.created", project_view(project, agent_count=1), wake=True)
        return project

    async def update_project(self, project_id: UUID, **fields: Any) -> Project:
        allowed = {"title", "repo", "label"}
        async with self.sessions() as session:
            project = await session.get(Project, project_id)
            if project is None:
                raise KeyError("project not found")
            for key, value in fields.items():
                if key not in allowed or value is None:
                    continue
                if key == "title":
                    value = str(value).strip()
                    if not value:
                        raise ValueError("title is required")
                elif key == "repo":
                    value = normalize_repo(str(value))
                elif key == "label":
                    value = str(value).strip() or "agent"
                setattr(project, key, value)
            if "repo" in fields and fields["repo"] is not None:
                for issue in (
                    await session.execute(select(Issue).where(Issue.project_id == project_id))
                ).scalars():
                    issue.repo = project.repo
            await session.commit()
            await session.refresh(project)
            await self.bus.publish("project.updated", project_view(project), wake=True)
            return project

    async def delete_project(self, project_id: UUID) -> None:
        async with self.sessions() as session:
            project = await session.get(Project, project_id)
            if project is None:
                raise KeyError("project not found")
            running = (
                await session.execute(
                    select(func.count(Agent.id)).where(Agent.project_id == project_id, Agent.status == AGENT_RUNNING)
                )
            ).scalar_one()
            if running:
                raise ValueError("cannot delete a project with a running agent")
            issue_ids = list(
                (await session.execute(select(Issue.id).where(Issue.project_id == project_id))).scalars()
            )
            if issue_ids:
                run_ids = list((await session.execute(select(Run.id).where(Run.issue_id.in_(issue_ids)))).scalars())
                if run_ids:
                    await session.execute(delete(Message).where(Message.run_id.in_(run_ids)))
                    await session.execute(delete(Run).where(Run.id.in_(run_ids)))
                await session.execute(delete(Issue).where(Issue.id.in_(issue_ids)))
            await session.execute(delete(Agent).where(Agent.project_id == project_id))
            await session.delete(project)
            await session.commit()
        await self.bus.publish("project.deleted", {"id": str(project_id)}, wake=True)

    async def seed_agent(self, project_id: UUID, name: str) -> Agent:
        async with self.sessions() as session:
            existing = (
                await session.execute(select(Agent).where(Agent.project_id == project_id, Agent.name == name))
            ).scalar_one_or_none()
            if existing:
                if not getattr(existing, "avatar_seed", ""):
                    existing.avatar_seed = secrets.token_hex(8)
                    await session.commit()
                    await session.refresh(existing)
                return existing
            agent = Agent(project_id=project_id, name=name, status=AGENT_IDLE, avatar_seed=secrets.token_hex(8))
            session.add(agent)
            await session.commit()
            await session.refresh(agent)
            await self.bus.publish("agent.created", agent_view(agent), wake=True)
            return agent

    async def list_agents(self, project_id: UUID | None = None) -> list[Agent]:
        async with self.sessions() as session:
            q = select(Agent).order_by(Agent.created_at)
            if project_id is not None:
                q = q.where(Agent.project_id == project_id)
            return list((await session.execute(q)).scalars())

    async def get_agent(self, agent_id: UUID) -> Agent | None:
        async with self.sessions() as session:
            return await session.get(Agent, agent_id)

    async def add_agent(
        self,
        name: str,
        *,
        project_id: UUID,
        persona: str = "",
        instructions: str = "",
        mcp_servers: list | None = None,
        paused: bool = False,
        avatar_seed: str | None = None,
    ) -> Agent:
        async with self.sessions() as session:
            project = await session.get(Project, project_id)
            if project is None:
                raise KeyError("project not found")
            agent = Agent(
                project_id=project_id,
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

    async def upsert_issue(self, project: Project, item: dict[str, Any]) -> Issue:
        number = int(item["number"])
        async with self.sessions() as session:
            issue = (
                await session.execute(select(Issue).where(Issue.repo == project.repo, Issue.number == number))
            ).scalar_one_or_none()
            if issue is None:
                issue = Issue(project_id=project.id, repo=project.repo, number=number)
                session.add(issue)
            issue.project_id = project.id
            issue.repo = project.repo
            issue.title = str(item.get("title") or "")
            issue.body = str(item.get("body") or "")
            issue.html_url = str(item.get("url") or "")
            issue.labels_json = item.get("labels") or []
            issue.state = str(item.get("state") or "open").lower()
            issue.github_updated_at = str(item.get("updatedAt") or "")
            await session.commit()
            await session.refresh(issue)
            await self.bus.publish("issue.updated", {"id": str(issue.id), "number": issue.number, "project_id": str(project.id)})
            return issue

    async def mark_missing_closed(self, project: Project, seen: list[int]) -> None:
        async with self.sessions() as session:
            q = select(Issue).where(Issue.project_id == project.id, Issue.state == "open")
            if seen:
                q = q.where(Issue.number.not_in(seen))
            rows = list((await session.execute(q)).scalars())
            for issue in rows:
                issue.state = "closed"
            await session.commit()

    async def list_issues(self, project_id: UUID) -> list[Issue]:
        async with self.sessions() as session:
            return list(
                (
                    await session.execute(
                        select(Issue).where(Issue.project_id == project_id).order_by(Issue.number.desc())
                    )
                ).scalars()
            )

    async def get_issue(self, issue_id: UUID) -> Issue | None:
        async with self.sessions() as session:
            return (
                await session.execute(select(Issue).options(selectinload(Issue.project)).where(Issue.id == issue_id))
            ).scalar_one_or_none()

    async def get_issue_by_number(self, project_id: UUID, number: int) -> Issue | None:
        async with self.sessions() as session:
            return (
                await session.execute(
                    select(Issue)
                    .options(selectinload(Issue.project))
                    .where(Issue.project_id == project_id, Issue.number == number)
                )
            ).scalar_one_or_none()

    def _active_run_query(self, issue_id: UUID) -> Select[tuple[Run]]:
        return select(Run).where(Run.issue_id == issue_id, Run.status.in_((TASK_QUEUED, TASK_RUNNING)))

    async def active_run_for_issue(self, issue_id: UUID) -> Run | None:
        async with self.sessions() as session:
            return (await session.execute(self._active_run_query(issue_id))).scalar_one_or_none()

    async def latest_run_for_issue(self, issue_id: UUID) -> Run | None:
        async with self.sessions() as session:
            return (
                await session.execute(
                    select(Run)
                    .options(selectinload(Run.issue), selectinload(Run.agent))
                    .where(Run.issue_id == issue_id)
                    .order_by(Run.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()

    async def list_runs_for_issue(self, issue_id: UUID) -> list[Run]:
        async with self.sessions() as session:
            return list(
                (
                    await session.execute(
                        select(Run)
                        .options(selectinload(Run.issue), selectinload(Run.agent))
                        .where(Run.issue_id == issue_id)
                        .order_by(Run.created_at.desc())
                    )
                ).scalars()
            )

    async def oldest_queued(self, project_id: UUID) -> Run | None:
        async with self.sessions() as session:
            return (
                await session.execute(
                    select(Run)
                    .join(Issue, Run.issue_id == Issue.id)
                    .options(selectinload(Run.issue), selectinload(Run.agent))
                    .where(Run.status == TASK_QUEUED, Issue.project_id == project_id)
                    .order_by(Run.created_at.asc())
                    .limit(1)
                )
            ).scalar_one_or_none()

    async def oldest_eligible_issue(self, project: Project) -> Issue | None:
        async with self.sessions() as session:
            issues = list(
                (
                    await session.execute(
                        select(Issue)
                        .where(Issue.project_id == project.id, Issue.state == "open")
                        .order_by(Issue.github_updated_at.asc())
                    )
                ).scalars()
            )
            for issue in issues:
                if not has_label(issue.labels_json, project.label):
                    continue
                existing = (await session.execute(select(Run.id).where(Run.issue_id == issue.id).limit(1))).first()
                if existing is None:
                    return issue
            return None

    async def idle_agents(self, project_id: UUID | None = None) -> list[Agent]:
        async with self.sessions() as session:
            q = select(Agent).where(Agent.status == AGENT_IDLE, Agent.paused.is_(False)).order_by(Agent.created_at)
            if project_id is not None:
                q = q.where(Agent.project_id == project_id)
            return list((await session.execute(q)).scalars())

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
                    select(Run)
                    .options(selectinload(Run.issue).selectinload(Issue.project), selectinload(Run.agent))
                    .where(Run.id == run_id)
                )
            ).scalar_one_or_none()

    async def list_runs(
        self,
        *,
        project_id: UUID | None = None,
        agent_id: UUID | None = None,
        issue_id: UUID | None = None,
        limit: int = 80,
    ) -> list[Run]:
        async with self.sessions() as session:
            q = select(Run).options(selectinload(Run.issue), selectinload(Run.agent)).order_by(Run.created_at.desc())
            if issue_id is not None:
                q = q.where(Run.issue_id == issue_id)
            if agent_id is not None:
                q = q.where(Run.agent_id == agent_id)
            if project_id is not None:
                q = q.join(Issue, Run.issue_id == Issue.id).where(Issue.project_id == project_id)
            return list((await session.execute(q.limit(limit))).scalars())

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
                    select(Run)
                    .options(selectinload(Run.issue).selectinload(Issue.project), selectinload(Run.agent))
                    .where(Run.id == run_id)
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
