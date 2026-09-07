"""Create/upgrade tables for installs that rely on create_all."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncConnection

from shatun.models import Base

_ALTERS = (
    "ALTER TABLE agents ADD COLUMN IF NOT EXISTS paused BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE agents ADD COLUMN IF NOT EXISTS persona TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE agents ADD COLUMN IF NOT EXISTS instructions TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE agents ADD COLUMN IF NOT EXISTS avatar_seed VARCHAR(32) NOT NULL DEFAULT ''",
    "ALTER TABLE agents ADD COLUMN IF NOT EXISTS mcp_servers JSONB NOT NULL DEFAULT '[]'::jsonb",
    "ALTER TABLE agents ADD COLUMN IF NOT EXISTS project_id UUID",
    "ALTER TABLE issues ADD COLUMN IF NOT EXISTS project_id UUID",
    "ALTER TABLE agents DROP CONSTRAINT IF EXISTS agents_name_key",
    "CREATE INDEX IF NOT EXISTS ix_agents_project_id ON agents (project_id)",
    "CREATE INDEX IF NOT EXISTS ix_issues_project_id ON issues (project_id)",
)


async def bootstrap_schema(conn: AsyncConnection) -> None:
    await conn.run_sync(Base.metadata.create_all)
    for stmt in _ALTERS:
        await conn.exec_driver_sql(stmt)
