"""SQLAlchemy 2 models."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

TASK_QUEUED = "queued"
TASK_RUNNING = "running"
TASK_SUCCEEDED = "succeeded"
TASK_FAILED = "failed"
TASK_STOPPED = "stopped"

AGENT_IDLE = "idle"
AGENT_RUNNING = "running"
AGENT_OFFLINE = "offline"
AGENT_OOO = "ooo"

PHASE_QUEUED = "queued"
PHASE_CLONING = "cloning"
PHASE_HANDSHAKE = "handshake"
PHASE_PROMPTING = "prompting"
PHASE_DONE = "done"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class AppSettings(TimestampMixin, Base):
    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    grok_bin: Mapped[str] = mapped_column(String(200), default="grok")
    grok_args: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    xai_api_key: Mapped[str] = mapped_column(Text, default="")
    poll_seconds: Mapped[int] = mapped_column(Integer, default=60)
    scheduler_seconds: Mapped[int] = mapped_column(Integer, default=5)
    run_timeout_sec: Mapped[int] = mapped_column(Integer, default=2700)
    default_agent_name: Mapped[str] = mapped_column(String(80), default="Bob")


class Project(TimestampMixin, Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(200))
    repo: Mapped[str] = mapped_column(String(200), unique=True)
    label: Mapped[str] = mapped_column(String(80), default="agent")
    agents: Mapped[list[Agent]] = relationship(back_populates="project")
    issues: Mapped[list[Issue]] = relationship(back_populates="project")


class Agent(TimestampMixin, Base):
    __tablename__ = "agents"
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_agents_project_name"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(32), default=AGENT_IDLE)
    paused: Mapped[bool] = mapped_column(Boolean, default=False)
    persona: Mapped[str] = mapped_column(Text, default="")
    instructions: Mapped[str] = mapped_column(Text, default="")
    avatar_seed: Mapped[str] = mapped_column(String(32), default="")
    mcp_servers: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    current_run_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    project: Mapped[Project] = relationship(back_populates="agents")
    runs: Mapped[list[Run]] = relationship(back_populates="agent")


class Issue(TimestampMixin, Base):
    __tablename__ = "issues"
    __table_args__ = (UniqueConstraint("repo", "number", name="uq_issues_repo_number"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    repo: Mapped[str] = mapped_column(String(200))
    number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(500), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    html_url: Mapped[str] = mapped_column(String(500), default="")
    labels_json: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    state: Mapped[str] = mapped_column(String(32), default="open")
    github_updated_at: Mapped[str] = mapped_column(String(64), default="")
    project: Mapped[Project] = relationship(back_populates="issues")
    runs: Mapped[list[Run]] = relationship(back_populates="issue")


class Run(TimestampMixin, Base):
    __tablename__ = "runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    issue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("issues.id"))
    agent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agents.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default=TASK_QUEUED)
    phase: Mapped[str] = mapped_column(String(32), default=PHASE_QUEUED)
    pid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cwd: Mapped[str | None] = mapped_column(Text, nullable=True)
    log_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    pr_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    issue: Mapped[Issue] = relationship(back_populates="runs")
    agent: Mapped[Agent | None] = relationship(back_populates="runs")
    messages: Mapped[list[Message]] = relationship(back_populates="run", cascade="all, delete-orphan")


class Message(TimestampMixin, Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    tool_call_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    title: Mapped[str | None] = mapped_column(String(300), nullable=True)
    status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    text: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    run: Mapped[Run] = relationship(back_populates="messages")
