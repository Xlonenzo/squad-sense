"""JiraMockClient — implementação in-memory persistida em JSON.

Usado quando JIRA_MOCK=true. Permite rodar o app inteiro offline e plantar
issues com timestamps históricos arbitrários (algo que o Jira Cloud real
não permite — created_at é sempre 'agora' do ponto de vista da API).
"""

import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.exceptions import JiraClientError
from app.core.logging import get_logger
from app.schemas.jira import (
    Issue,
    IssueCreatePayload,
    IssueStatus,
    IssueType,
    JiraComment,
    Project,
    Sprint,
    SprintState,
    User,
)

log = get_logger(__name__)


_DEFAULT_USER = User(
    account_id="mock-user-001",
    display_name="Mock Admin",
    email_address="mock-admin@squad-sense.local",
)


class JiraMockClient:
    mode = "mock"

    def __init__(self, state_path: Path):
        self.state_path = Path(state_path)
        self._lock = asyncio.Lock()
        self._state: dict[str, Any] = self._load()

    # ------------------------------------------------------------------ state

    def _load(self) -> dict[str, Any]:
        if self.state_path.exists():
            try:
                return json.loads(self.state_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as e:
                raise JiraClientError(f"mock state inválido: {e}") from e
        return self._empty_state()

    @staticmethod
    def _empty_state() -> dict[str, Any]:
        return {
            "users": [_DEFAULT_USER.model_dump()],
            "projects": {},
            "sprints": {},
            "issues": {},
            "next_issue_number": {},
            "comments": [],
        }

    def _persist(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps(self._state, indent=2, default=str, ensure_ascii=False),
            encoding="utf-8",
        )

    # ------------------------------------------------------------------ users

    async def get_myself(self) -> User:
        return _DEFAULT_USER

    # --------------------------------------------------------------- projects

    async def get_project(self, key: str) -> Project | None:
        async with self._lock:
            raw = self._state["projects"].get(key)
            return Project(**raw) if raw else None

    async def create_project(
        self,
        key: str,
        name: str,
        lead_account_id: str | None = None,
    ) -> Project:
        async with self._lock:
            if key in self._state["projects"]:
                raise JiraClientError(f"projeto {key} já existe", code="project_exists")

            project = Project(
                id=str(uuid.uuid4()),
                key=key,
                name=name,
                lead=_DEFAULT_USER,
            )
            self._state["projects"][key] = project.model_dump()
            self._state["next_issue_number"][key] = 1
            self._persist()
            log.info("mock_project_created", key=key, name=name)
            return project

    # --------------------------------------------------------------- sprints

    async def list_sprints(self, project_key: str) -> list[Sprint]:
        async with self._lock:
            return [
                Sprint(**s)
                for s in self._state["sprints"].values()
                if s.get("project_key") == project_key
            ]

    async def create_sprint(
        self,
        project_key: str,
        name: str,
        *,
        goal: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        state: SprintState = SprintState.FUTURE,
    ) -> Sprint:
        async with self._lock:
            if project_key not in self._state["projects"]:
                raise JiraClientError(f"projeto {project_key} não existe")

            sprint_id = f"sprint-{uuid.uuid4().hex[:8]}"
            sprint = Sprint(
                id=sprint_id,
                name=name,
                state=state,
                goal=goal,
                start_date=start_date,
                end_date=end_date,
            )
            stored = sprint.model_dump()
            stored["project_key"] = project_key  # extensão interna do mock
            self._state["sprints"][sprint_id] = stored
            self._persist()
            return sprint

    async def update_sprint_state(
        self,
        sprint_id: str,
        state: SprintState,
        complete_date: datetime | None = None,
    ) -> Sprint:
        async with self._lock:
            raw = self._state["sprints"].get(sprint_id)
            if not raw:
                raise JiraClientError(f"sprint {sprint_id} não existe")
            raw["state"] = state.value
            if complete_date:
                raw["complete_date"] = complete_date.isoformat()
            self._persist()
            return Sprint(**{k: v for k, v in raw.items() if k != "project_key"})

    # ---------------------------------------------------------------- issues

    async def create_issue(self, payload: IssueCreatePayload) -> Issue:
        async with self._lock:
            project_key = payload.project_key
            if project_key not in self._state["projects"]:
                raise JiraClientError(f"projeto {project_key} não existe")

            n = self._state["next_issue_number"].get(project_key, 1)
            self._state["next_issue_number"][project_key] = n + 1
            issue_key = f"{project_key}-{n}"

            now = datetime.now(timezone.utc)
            created_at = payload.created_at or now
            updated_at = payload.updated_at or created_at

            assignee = self._user_lookup(payload.assignee_account_id)
            reporter = _DEFAULT_USER

            issue = Issue(
                id=str(uuid.uuid4()),
                key=issue_key,
                project_key=project_key,
                summary=payload.summary,
                description=payload.description,
                issue_type=payload.issue_type,
                status=payload.status or IssueStatus.TODO,
                labels=list(payload.labels),
                assignee=assignee,
                reporter=reporter,
                story_points_estimated=payload.story_points,
                story_points_actual=payload.story_points_actual,
                sprint_id=payload.sprint_id,
                epic_key=payload.epic_key,
                created_at=created_at,
                updated_at=updated_at,
                last_activity_at=updated_at,
                resolved_at=payload.resolved_at,
            )
            self._state["issues"][issue_key] = json.loads(issue.model_dump_json())
            self._persist()
            return issue

    async def update_issue(
        self,
        key: str,
        *,
        status: IssueStatus | None = None,
        story_points_actual: float | None = None,
        resolved_at: datetime | None = None,
        last_activity_at: datetime | None = None,
    ) -> Issue:
        async with self._lock:
            raw = self._state["issues"].get(key)
            if not raw:
                raise JiraClientError(f"issue {key} não existe")
            if status is not None:
                raw["status"] = status.value
            if story_points_actual is not None:
                raw["story_points_actual"] = story_points_actual
            if resolved_at is not None:
                raw["resolved_at"] = resolved_at.isoformat()
            if last_activity_at is not None:
                raw["last_activity_at"] = last_activity_at.isoformat()
                raw["updated_at"] = last_activity_at.isoformat()
            self._persist()
            return Issue(**raw)

    async def search_issues(
        self,
        project_key: str,
        *,
        sprint_id: str | None = None,
        status: IssueStatus | None = None,
        max_results: int = 200,
    ) -> list[Issue]:
        async with self._lock:
            results: list[Issue] = []
            for raw in self._state["issues"].values():
                if raw["project_key"] != project_key:
                    continue
                if sprint_id is not None and raw.get("sprint_id") != sprint_id:
                    continue
                if status is not None and raw.get("status") != status.value:
                    continue
                results.append(Issue(**raw))
                if len(results) >= max_results:
                    break
            return results

    # ------------------------------------------------------------- comments

    async def add_comment(self, issue_key: str, body: str) -> JiraComment:
        async with self._lock:
            if issue_key not in self._state["issues"]:
                raise JiraClientError(f"issue {issue_key} não existe")
            comment_id = f"c-{uuid.uuid4().hex[:12]}"
            now = datetime.now(timezone.utc)
            comment = JiraComment(
                id=comment_id,
                issue_key=issue_key,
                body=body,
                author=_DEFAULT_USER,
                created_at=now,
            )
            self._state.setdefault("comments", []).append(
                json.loads(comment.model_dump_json())
            )
            self._persist()
            return comment

    async def list_comments(self, issue_key: str) -> list[JiraComment]:
        async with self._lock:
            return [
                JiraComment(**c)
                for c in self._state.get("comments", [])
                if c.get("issue_key") == issue_key
            ]

    async def close(self) -> None:
        return None

    # --------------------------------------------------------------- helpers

    def _user_lookup(self, account_id: str | None) -> User | None:
        if not account_id:
            return None
        for u in self._state["users"]:
            if u["account_id"] == account_id:
                return User(**u)
        # Auto-cria usuário sintético — útil para o seed plantar joão.dev etc.
        synthetic = User(
            account_id=account_id,
            display_name=account_id,
            email_address=f"{account_id}@squad-sense.local",
        )
        self._state["users"].append(synthetic.model_dump())
        return synthetic

    @property
    def issue_type(self) -> type[IssueType]:
        return IssueType
