"""Modelos ORM (SQLAlchemy 2.0 declarative)."""

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.config import settings


class Base(DeclarativeBase):
    pass


class ProjectRow(Base):
    __tablename__ = "project"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    jira_id: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )

    sprints: Mapped[list["SprintRow"]] = relationship(back_populates="project")
    issues: Mapped[list["IssueRow"]] = relationship(back_populates="project")


class SprintRow(Base):
    __tablename__ = "sprint"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    jira_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"))

    name: Mapped[str] = mapped_column(String(200))
    state: Mapped[str] = mapped_column(String(20))
    goal: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    complete_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    project: Mapped["ProjectRow"] = relationship(back_populates="sprints")
    issues: Mapped[list["IssueRow"]] = relationship(back_populates="sprint")


class IssueRow(Base):
    __tablename__ = "issue"
    __table_args__ = (
        Index("ix_issue_project_status", "project_id", "status"),
        Index("ix_issue_assignee", "assignee_account_id"),
        Index("ix_issue_sprint", "sprint_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    jira_id: Mapped[str] = mapped_column(String(64), unique=True)
    key: Mapped[str] = mapped_column(String(40), unique=True, index=True)

    project_id: Mapped[int] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"))
    sprint_id: Mapped[int | None] = mapped_column(
        ForeignKey("sprint.id", ondelete="SET NULL"), nullable=True
    )
    epic_key: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)

    summary: Mapped[str] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    issue_type: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(30))

    labels: Mapped[list[str]] = mapped_column(JSON, default=list)
    components: Mapped[list[str]] = mapped_column(JSON, default=list)

    assignee_account_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    assignee_display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    reporter_account_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    story_points_estimated: Mapped[float | None] = mapped_column(Float, nullable=True)
    story_points_actual: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # hash do texto que entra no embedding — usado para evitar reembedding desnecessário
    text_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    project: Mapped["ProjectRow"] = relationship(back_populates="issues")
    sprint: Mapped["SprintRow | None"] = relationship(back_populates="issues")
    embedding: Mapped["IssueEmbeddingRow | None"] = relationship(
        back_populates="issue", uselist=False, cascade="all, delete-orphan"
    )


class RecommendationRow(Base):
    """Recomendação gerada pelo Coach Agent. Núcleo do closed loop:
    cada uma carrega seu status (proposed/accepted/rejected) e
    eventualmente o feedback humano que treina o agente para esse time."""

    __tablename__ = "recommendation"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("project.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default="proposed", index=True)
    severity: Mapped[str] = mapped_column(String(10))
    confidence: Mapped[float] = mapped_column(Float)

    target_keys: Mapped[list[str]] = mapped_column(JSON, default=list)
    summary: Mapped[str] = mapped_column(String(500))
    comment_body: Mapped[str] = mapped_column(Text)

    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    evidence_issue_keys: Mapped[list[str]] = mapped_column(JSON, default=list)

    model_used: Mapped[str] = mapped_column(String(80))

    human_feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    jira_comment_id: Mapped[str | None] = mapped_column(String(120), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )


class IssueEmbeddingRow(Base):
    __tablename__ = "issue_embedding"
    __table_args__ = (
        UniqueConstraint("issue_id", name="uq_issue_embedding_issue"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    issue_id: Mapped[int] = mapped_column(ForeignKey("issue.id", ondelete="CASCADE"))
    model: Mapped[str] = mapped_column(String(60))
    text_hash: Mapped[str] = mapped_column(String(64), index=True)
    embedding: Mapped[list[float]] = mapped_column(Vector(settings.embedding_dim))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )

    issue: Mapped["IssueRow"] = relationship(back_populates="embedding")
