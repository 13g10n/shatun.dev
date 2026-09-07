"""projects, app settings, and project-scoped agents/issues

Revision ID: 003
Revises: 002
Create Date: 2026-09-07
"""

from __future__ import annotations

import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("grok_bin", sa.String(length=200), nullable=False, server_default="grok"),
        sa.Column("grok_args", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='["agent","--always-approve","--no-leader","stdio"]'),
        sa.Column("xai_api_key", sa.Text(), nullable=False, server_default=""),
        sa.Column("poll_seconds", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("scheduler_seconds", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("run_timeout_sec", sa.Integer(), nullable=False, server_default="2700"),
        sa.Column("default_agent_name", sa.String(length=80), nullable=False, server_default="Bob"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "projects",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("repo", sa.String(length=200), nullable=False, unique=True),
        sa.Column("label", sa.String(length=80), nullable=False, server_default="agent"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.add_column("agents", sa.Column("project_id", sa.Uuid(), nullable=True))
    op.add_column("issues", sa.Column("project_id", sa.Uuid(), nullable=True))
    op.drop_constraint("agents_name_key", "agents", type_="unique")

    bind = op.get_bind()
    issues = bind.execute(sa.text("SELECT DISTINCT repo FROM issues ORDER BY repo")).fetchall()
    repo = issues[0][0] if issues else None
    if repo is None:
        agents_exist = bind.execute(sa.text("SELECT 1 FROM agents LIMIT 1")).first()
        if agents_exist:
            repo = "imported/local"
    if repo:
        project_id = uuid.uuid4()
        title = str(repo).split("/")[-1] or "Imported"
        bind.execute(
            sa.text("INSERT INTO projects (id, title, repo, label, created_at, updated_at) VALUES (:id, :title, :repo, 'agent', NOW(), NOW())"),
            {"id": project_id, "title": title, "repo": repo},
        )
        bind.execute(sa.text("UPDATE agents SET project_id = :id WHERE project_id IS NULL"), {"id": project_id})
        bind.execute(sa.text("UPDATE issues SET project_id = :id WHERE project_id IS NULL"), {"id": project_id})

    op.create_index("ix_agents_project_id", "agents", ["project_id"])
    op.create_index("ix_issues_project_id", "issues", ["project_id"])
    op.create_index("ix_agents_project_name", "agents", ["project_id", "name"], unique=True)
    op.create_foreign_key("agents_project_id_fkey", "agents", "projects", ["project_id"], ["id"], ondelete="CASCADE")
    op.create_foreign_key("issues_project_id_fkey", "issues", "projects", ["project_id"], ["id"], ondelete="CASCADE")


def downgrade() -> None:
    op.drop_constraint("issues_project_id_fkey", "issues", type_="foreignkey")
    op.drop_constraint("agents_project_id_fkey", "agents", type_="foreignkey")
    op.drop_index("ix_agents_project_name", table_name="agents")
    op.drop_index("ix_issues_project_id", table_name="issues")
    op.drop_index("ix_agents_project_id", table_name="agents")
    op.drop_column("issues", "project_id")
    op.drop_column("agents", "project_id")
    op.create_unique_constraint("agents_name_key", "agents", ["name"])
    op.drop_table("projects")
    op.drop_table("app_settings")
