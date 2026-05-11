"""Protocol comum aos clientes Jira (REST real e Mock).

Tudo que o resto do app consome passa por esta interface, então a troca
mock ↔ real é transparente para services e routers.
"""

from datetime import datetime
from typing import Protocol, runtime_checkable

from app.config import settings
from app.schemas.jira import (
    Issue,
    IssueCreatePayload,
    IssueStatus,
    JiraComment,
    Project,
    Sprint,
    SprintState,
    User,
)


@runtime_checkable
class JiraClient(Protocol):
    mode: str  # 'rest' ou 'mock'

    async def get_myself(self) -> User: ...

    async def get_project(self, key: str) -> Project | None: ...

    async def create_project(
        self,
        key: str,
        name: str,
        lead_account_id: str | None = None,
    ) -> Project: ...

    async def list_sprints(self, project_key: str) -> list[Sprint]: ...

    async def create_sprint(
        self,
        project_key: str,
        name: str,
        *,
        goal: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        state: SprintState = SprintState.FUTURE,
    ) -> Sprint: ...

    async def update_sprint_state(
        self,
        sprint_id: str,
        state: SprintState,
        complete_date: datetime | None = None,
    ) -> Sprint: ...

    async def create_issue(self, payload: IssueCreatePayload) -> Issue: ...

    async def update_issue(
        self,
        key: str,
        *,
        status: IssueStatus | None = None,
        story_points_actual: float | None = None,
        resolved_at: datetime | None = None,
        last_activity_at: datetime | None = None,
    ) -> Issue: ...

    async def search_issues(
        self,
        project_key: str,
        *,
        sprint_id: str | None = None,
        status: IssueStatus | None = None,
        max_results: int = 200,
    ) -> list[Issue]: ...

    async def add_comment(self, issue_key: str, body: str) -> JiraComment: ...

    async def list_comments(self, issue_key: str) -> list[JiraComment]: ...

    async def close(self) -> None: ...


def make_jira_client() -> JiraClient:
    """Factory: escolhe mock ou REST com base em settings.jira_mock."""
    if settings.jira_mock:
        from app.clients.jira_mock import JiraMockClient

        return JiraMockClient(state_path=settings.mock_state_path)

    from app.clients.jira_rest import JiraRestClient

    return JiraRestClient()
