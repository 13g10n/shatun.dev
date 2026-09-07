"""JSON views for API and Socket.IO."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from shatun.models import Agent, AppSettings, Issue, Message, Project, Run


def _id(value: UUID | None) -> str | None:
    return str(value) if value else None


def _dt(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def has_label(labels: Any, label: str) -> bool:
    if not isinstance(labels, list):
        return False
    for item in labels:
        if isinstance(item, dict) and item.get("name") == label:
            return True
        if item == label:
            return True
    return False


def agent_display_status(agent: Agent) -> str:
    if agent.status == "running":
        return "running"
    if getattr(agent, "paused", False):
        return "ooo"
    if agent.status == "offline":
        return "offline"
    return "idle"


def settings_view(settings: AppSettings) -> dict[str, Any]:
    return {
        "grok_bin": settings.grok_bin,
        "grok_args": list(settings.grok_args or []),
        "xai_api_key": settings.xai_api_key or "",
        "poll_seconds": settings.poll_seconds,
        "scheduler_seconds": settings.scheduler_seconds,
        "run_timeout_sec": settings.run_timeout_sec,
        "default_agent_name": settings.default_agent_name,
        "updated_at": _dt(settings.updated_at),
    }


def project_view(project: Project, *, agent_count: int = 0, running: int = 0, task_count: int = 0) -> dict[str, Any]:
    return {
        "id": str(project.id),
        "title": project.title,
        "repo": project.repo,
        "label": project.label,
        "agent_count": agent_count,
        "running": running,
        "task_count": task_count,
        "created_at": _dt(project.created_at),
        "updated_at": _dt(project.updated_at),
    }


def agent_view(agent: Agent) -> dict[str, Any]:
    return {
        "id": str(agent.id),
        "project_id": _id(getattr(agent, "project_id", None)),
        "name": agent.name,
        "status": agent.status,
        "display_status": agent_display_status(agent),
        "paused": bool(getattr(agent, "paused", False)),
        "persona": getattr(agent, "persona", "") or "",
        "instructions": getattr(agent, "instructions", "") or "",
        "avatar_seed": getattr(agent, "avatar_seed", "") or str(agent.id),
        "mcp_servers": list(getattr(agent, "mcp_servers", None) or []),
        "current_run_id": _id(agent.current_run_id),
        "created_at": _dt(agent.created_at),
        "updated_at": _dt(agent.updated_at),
    }


def issue_view(issue: Issue, *, label: str, active_run: Run | None = None) -> dict[str, Any]:
    return {
        "id": str(issue.id),
        "project_id": _id(getattr(issue, "project_id", None)),
        "repo": issue.repo,
        "number": issue.number,
        "title": issue.title,
        "body": issue.body,
        "html_url": issue.html_url,
        "state": issue.state,
        "updated_at": issue.github_updated_at,
        "labels": issue.labels_json,
        "active_run_id": _id(active_run.id) if active_run else None,
        "active_run_status": active_run.status if active_run else None,
        "can_run": issue.state == "open" and has_label(issue.labels_json, label) and active_run is None,
    }


def task_view(issue: Issue, *, label: str, latest_run: Run | None = None, active_run: Run | None = None) -> dict[str, Any]:
    view = issue_view(issue, label=label, active_run=active_run)
    if active_run:
        status = active_run.status
    elif latest_run:
        status = latest_run.status
    elif view["can_run"]:
        status = "ready"
    else:
        status = issue.state
    view["latest_run"] = run_view(latest_run) if latest_run else None
    view["latest_run_id"] = _id(latest_run.id) if latest_run else None
    view["task_status"] = status
    return view


def run_view(run: Run) -> dict[str, Any]:
    issue = run.issue
    agent = run.agent
    return {
        "id": str(run.id),
        "issue_id": str(run.issue_id),
        "project_id": _id(getattr(issue, "project_id", None)) if issue else None,
        "repo": issue.repo if issue else None,
        "issue_number": issue.number if issue else None,
        "issue_title": issue.title if issue else None,
        "agent_id": _id(run.agent_id),
        "agent_name": agent.name if agent else None,
        "status": run.status,
        "phase": run.phase,
        "pid": run.pid,
        "started_at": _dt(run.started_at),
        "finished_at": _dt(run.finished_at),
        "exit_code": run.exit_code,
        "last_error": run.last_error,
        "pr_url": run.pr_url,
        "can_stop": run.status == "running",
        "can_requeue": run.status in ("failed", "stopped"),
        "created_at": _dt(run.created_at),
    }


def message_view(message: Message) -> dict[str, Any]:
    return {
        "id": str(message.id),
        "run_id": str(message.run_id),
        "kind": message.kind,
        "tool_call_id": message.tool_call_id,
        "title": message.title,
        "status": message.status,
        "text": message.text,
        "payload": message.payload,
        "created_at": _dt(message.created_at),
    }
