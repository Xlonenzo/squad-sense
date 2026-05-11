"""recommendation table (closed loop)

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-08

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "recommendation",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "project_id",
            sa.Integer,
            sa.ForeignKey("project.id", ondelete="CASCADE"),
            index=True,
            nullable=False,
        ),
        sa.Column("type", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="proposed", index=True),
        sa.Column("severity", sa.String(10), nullable=False),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("target_keys", sa.JSON, nullable=False),
        sa.Column("summary", sa.String(500), nullable=False),
        sa.Column("comment_body", sa.Text, nullable=False),
        sa.Column("evidence", sa.JSON, nullable=False),
        sa.Column("evidence_issue_keys", sa.JSON, nullable=False),
        sa.Column("model_used", sa.String(80), nullable=False),
        sa.Column("human_feedback", sa.Text, nullable=True),
        sa.Column("jira_comment_id", sa.String(120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("recommendation")
