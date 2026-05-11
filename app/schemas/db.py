"""Schemas de resposta das rotas /db/*. Distintos dos schemas Jira para
mantermos a fronteira clara entre 'forma da fonte' e 'forma derivada'."""

from datetime import datetime

from pydantic import BaseModel


class DbIssueOut(BaseModel):
    id: int
    key: str
    project_key: str
    summary: str
    issue_type: str
    status: str
    labels: list[str]
    assignee: str | None
    story_points_estimated: float | None
    sprint_id: int | None
    epic_key: str | None
    created_at: datetime
    has_embedding: bool


class SimilarHit(BaseModel):
    key: str
    summary: str
    issue_type: str
    status: str
    labels: list[str]
    distance: float  # cosine distance — quanto menor, mais parecido
    similarity: float  # 1 - distance
