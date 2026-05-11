"""initial schema (project, sprint, issue, issue_embedding com vector)

Revision ID: 0001
Revises:
Create Date: 2026-05-08

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

from app.config import settings

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "project",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("key", sa.String(20), unique=True, index=True, nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("jira_id", sa.String(64), unique=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "sprint",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("jira_id", sa.String(64), unique=True, index=True, nullable=False),
        sa.Column(
            "project_id",
            sa.Integer,
            sa.ForeignKey("project.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("goal", sa.Text, nullable=True),
        sa.Column("start_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("complete_date", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "issue",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("jira_id", sa.String(64), unique=True, nullable=False),
        sa.Column("key", sa.String(40), unique=True, index=True, nullable=False),
        sa.Column(
            "project_id",
            sa.Integer,
            sa.ForeignKey("project.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "sprint_id",
            sa.Integer,
            sa.ForeignKey("sprint.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("epic_key", sa.String(40), nullable=True, index=True),
        sa.Column("summary", sa.String(500), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("issue_type", sa.String(20), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("labels", sa.JSON, nullable=False),
        sa.Column("components", sa.JSON, nullable=False),
        sa.Column("assignee_account_id", sa.String(64), nullable=True),
        sa.Column("assignee_display_name", sa.String(120), nullable=True),
        sa.Column("reporter_account_id", sa.String(64), nullable=True),
        sa.Column("story_points_estimated", sa.Float, nullable=True),
        sa.Column("story_points_actual", sa.Float, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("text_hash", sa.String(64), nullable=True, index=True),
    )
    op.create_index("ix_issue_project_status", "issue", ["project_id", "status"])
    op.create_index("ix_issue_assignee", "issue", ["assignee_account_id"])
    op.create_index("ix_issue_sprint", "issue", ["sprint_id"])

    op.create_table(
        "issue_embedding",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "issue_id",
            sa.Integer,
            sa.ForeignKey("issue.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("model", sa.String(60), nullable=False),
        sa.Column("text_hash", sa.String(64), index=True, nullable=False),
        sa.Column("embedding", Vector(settings.embedding_dim), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("issue_id", name="uq_issue_embedding_issue"),
    )

    # Index ANN para busca por similaridade (cosine). lists=100 é OK para <100k issues.
    op.execute(
        "CREATE INDEX ix_issue_embedding_cosine "
        "ON issue_embedding USING ivfflat (embedding vector_cosine_ops) "
        "WITH (lists = 100)"
    )


def downgrade() -> None:
    op.drop_index("ix_issue_embedding_cosine", table_name="issue_embedding")
    op.drop_table("issue_embedding")
    op.drop_index("ix_issue_sprint", table_name="issue")
    op.drop_index("ix_issue_assignee", table_name="issue")
    op.drop_index("ix_issue_project_status", table_name="issue")
    op.drop_table("issue")
    op.drop_table("sprint")
    op.drop_table("project")
