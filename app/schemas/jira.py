"""Modelos normalizados de entidades Jira.

Tanto JiraRestClient (Jira Cloud real) quanto JiraMockClient retornam estas
shapes — é o contrato que o resto do app consome.
"""

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class IssueType(str, Enum):
    EPIC = "Epic"
    STORY = "Story"
    TASK = "Task"
    BUG = "Bug"


class IssueStatus(str, Enum):
    TODO = "To Do"
    IN_PROGRESS = "In Progress"
    CODE_REVIEW = "Code Review"
    DONE = "Done"


class SprintState(str, Enum):
    FUTURE = "future"
    ACTIVE = "active"
    CLOSED = "closed"


class User(BaseModel):
    account_id: str
    display_name: str
    email_address: str | None = None


class Project(BaseModel):
    id: str
    key: str
    name: str
    project_type_key: Literal["software"] = "software"
    lead: User | None = None


class Sprint(BaseModel):
    id: str
    name: str
    state: SprintState
    goal: str | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None
    complete_date: datetime | None = None


class Issue(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    key: str
    project_key: str
    summary: str
    description: str | None = None
    issue_type: IssueType
    status: IssueStatus = IssueStatus.TODO

    labels: list[str] = Field(default_factory=list)
    components: list[str] = Field(default_factory=list)

    assignee: User | None = None
    reporter: User | None = None

    story_points_estimated: float | None = None
    story_points_actual: float | None = None

    sprint_id: str | None = None
    epic_key: str | None = None

    created_at: datetime
    updated_at: datetime
    last_activity_at: datetime | None = None
    resolved_at: datetime | None = None


class JiraComment(BaseModel):
    id: str
    issue_key: str
    body: str
    author: User
    created_at: datetime


class IssueCreatePayload(BaseModel):
    """Payload para criar uma issue. Próximo do que o Jira aceita, mas normalizado."""

    project_key: str
    summary: str
    issue_type: IssueType
    description: str | None = None
    labels: list[str] = Field(default_factory=list)
    assignee_account_id: str | None = None
    story_points: float | None = None
    sprint_id: str | None = None
    epic_key: str | None = None
    # Para o seed plantar dados históricos com timestamps controlados.
    created_at: datetime | None = None
    updated_at: datetime | None = None
    status: IssueStatus | None = None
    story_points_actual: float | None = None
    resolved_at: datetime | None = None
