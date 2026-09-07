"""agent persona, mcp, pause, avatar

Revision ID: 002
Revises: 001
Create Date: 2026-09-07
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("agents", sa.Column("paused", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("agents", sa.Column("persona", sa.Text(), nullable=False, server_default=""))
    op.add_column("agents", sa.Column("instructions", sa.Text(), nullable=False, server_default=""))
    op.add_column("agents", sa.Column("avatar_seed", sa.String(length=32), nullable=False, server_default=""))
    op.add_column(
        "agents",
        sa.Column("mcp_servers", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("agents", "mcp_servers")
    op.drop_column("agents", "avatar_seed")
    op.drop_column("agents", "instructions")
    op.drop_column("agents", "persona")
    op.drop_column("agents", "paused")
