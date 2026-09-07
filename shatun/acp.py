"""ACP client using the official agent-client-protocol SDK.

Grok Build owns tools. We do not advertise fs/terminal capabilities.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from acp import PROTOCOL_VERSION, connect_to_agent
from acp.schema import (
    AgentMessageChunk,
    AgentPlanUpdate,
    AgentThoughtChunk,
    AllowedOutcome,
    ClientCapabilities,
    DeniedOutcome,
    FileSystemCapabilities,
    Implementation,
    PermissionOption,
    RequestPermissionResponse,
    TextContentBlock,
    ToolCallProgress,
    ToolCallStart,
    UsageUpdate,
)

log = logging.getLogger("shatun.acp")

OnEvent = Callable[[dict[str, Any]], Awaitable[None]]


def _text(content: Any) -> str:
    if isinstance(content, TextContentBlock):
        return content.text or ""
    if isinstance(content, dict):
        return str(content.get("text") or "")
    text = getattr(content, "text", None)
    return str(text) if text else ""


def _dump(obj: Any) -> dict[str, Any]:
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json", exclude_none=True)
    if isinstance(obj, dict):
        return obj
    return {"value": str(obj)}


class ShatunACPClient:
    """Minimal ACP client: observe session updates, auto-approve if asked."""

    def __init__(self, on_event: OnEvent) -> None:
        self.on_event = on_event

    async def session_update(self, session_id: str, update: Any, **kwargs: Any) -> None:
        event = self._classify(update)
        event["session_id"] = session_id
        await self.on_event(event)

    async def request_permission(
        self,
        session_id: str,
        tool_call: Any,
        options: list[PermissionOption],
        **kwargs: Any,
    ) -> RequestPermissionResponse:
        option = next((o for o in options if getattr(o, "kind", "") in {"allow_once", "allow_always"}), None)
        option = option or (options[0] if options else None)
        if option is None:
            return RequestPermissionResponse(outcome=DeniedOutcome(outcome="cancelled"))
        return RequestPermissionResponse(
            outcome=AllowedOutcome(option_id=option.option_id, outcome="selected")
        )

    def _classify(self, update: Any) -> dict[str, Any]:
        payload = _dump(update)
        if isinstance(update, AgentThoughtChunk):
            return {"kind": "thought", "text": _text(update.content), "payload": payload}
        if isinstance(update, AgentMessageChunk):
            return {"kind": "message", "text": _text(update.content), "payload": payload}
        if isinstance(update, ToolCallStart):
            return {
                "kind": "tool",
                "tool_call_id": update.tool_call_id,
                "title": update.title or update.kind or "tool",
                "status": update.status or "pending",
                "text": json.dumps(payload.get("rawInput") or payload.get("raw_input") or {}, default=str)[:4000],
                "payload": payload,
            }
        if isinstance(update, ToolCallProgress):
            return {
                "kind": "tool_update",
                "tool_call_id": update.tool_call_id,
                "title": update.title,
                "status": update.status or "in_progress",
                "text": json.dumps(payload.get("content") or payload, default=str)[:8000],
                "payload": payload,
            }
        if isinstance(update, AgentPlanUpdate):
            return {"kind": "plan", "text": json.dumps(payload, default=str)[:8000], "payload": payload}
        if isinstance(update, UsageUpdate):
            return {"kind": "usage", "payload": payload, "text": ""}
        name = type(update).__name__
        return {"kind": "session", "title": name, "text": "", "payload": payload}


async def connect_grok(client: ShatunACPClient, proc: Any):
    return connect_to_agent(client, proc.stdin, proc.stdout)


async def handshake(conn, cwd: str, api_key: str = "") -> str:
    init = await conn.initialize(
        protocol_version=PROTOCOL_VERSION,
        client_capabilities=ClientCapabilities(
            fs=FileSystemCapabilities(read_text_file=False, write_text_file=False),
            terminal=False,
        ),
        client_info=Implementation(name="shatun", version="0.1.0"),
    )
    methods = [m.id for m in (init.auth_methods or [])]
    if methods:
        method_id = "xai.api_key" if api_key and "xai.api_key" in methods else "cached_token"
        try:
            await conn.authenticate(method_id=method_id, headless=True)
        except Exception:
            log.exception("authenticate failed; trying session/new anyway")
    session = await conn.new_session(cwd=cwd, mcp_servers=[], autoMode=True)
    return session.session_id
