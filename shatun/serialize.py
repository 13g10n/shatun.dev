"""JSON views for API and Socket.IO."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from shatun.models import Agent, Issue, Message, Run


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


def agent_view(agent: Agent) -> dict[str, Any]:
    return {
        "id": str(agent.id),
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
        "number": issue.number,
        "title": issue.title,
        "html_url": issue.html_url,
        "state": issue.state,
        "updated_at": issue.github_updated_at,
        "labels": issue.labels_json,
        "active_run_id": _id(active_run.id) if active_run else None,
        "active_run_status": active_run.status if active_run else None,
        "can_run": issue.state == "open" and has_label(issue.labels_json, label) and active_run is None,
    }


def run_view(run: Run) -> dict[str, Any]:
    issue = run.issue
    agent = run.agent
    return {
        "id": str(run.id),
        "issue_id": str(run.issue_id),
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
