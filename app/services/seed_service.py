from datetime import datetime, timedelta, timezone

from app.clients.jira_client import JiraClient
from app.config import settings
from app.core.exceptions import BootstrapError
from app.core.logging import get_logger
from app.schemas.bootstrap import BootstrapSeedResponse
from app.schemas.jira import IssueCreatePayload, IssueStatus
from app.seed_data.synthetic_sprint import (
    PLANTED_PATTERNS,
    SeedIssue,
    SeedSprint,
    build_dataset,
)

log = get_logger(__name__)


class SeedService:
    def __init__(self, jira: JiraClient):
        self.jira = jira

    async def seed(self) -> BootstrapSeedResponse:
        if self.jira.mode != "mock":
            raise BootstrapError(
                "Seed sintético longitudinal exige timestamps retroativos, "
                "que o Jira Cloud não permite via API. Rode com JIRA_MOCK=true.",
                code="seed_requires_mock",
            )

        project_key = settings.jira_project_key
        project = await self.jira.get_project(project_key)
        if project is None:
            raise BootstrapError(
                f"projeto {project_key} não existe — chame /bootstrap/project antes."
            )

        now = datetime.now(timezone.utc)
        sprints, epics, stories = build_dataset(now=now)

        # 1) Sprints
        sprint_ids = await self._create_sprints(project_key, sprints)

        # 2) Epics
        epic_keys = await self._create_epics(project_key, epics, now)

        # 3) Stories / Tasks
        issues_created = await self._create_stories(project_key, stories, sprint_ids, epic_keys, now)

        log.info(
            "seed_complete",
            project_key=project_key,
            sprints=len(sprint_ids),
            epics=len(epic_keys),
            issues=issues_created,
        )

        return BootstrapSeedResponse(
            project_key=project_key,
            sprints_created=len(sprint_ids),
            issues_created=issues_created,
            epics_created=len(epic_keys),
            mode=self.jira.mode,
            planted_patterns=PLANTED_PATTERNS,
        )

    # ------------------------------------------------------------- sprints

    async def _create_sprints(
        self, project_key: str, sprints: list[SeedSprint]
    ) -> list[str]:
        ids: list[str] = []
        for s in sprints:
            sprint = await self.jira.create_sprint(
                project_key=project_key,
                name=s.name,
                goal=s.goal,
                start_date=s.start_date,
                end_date=s.end_date,
                state=s.state,
            )
            if s.complete_date:
                await self.jira.update_sprint_state(
                    sprint_id=sprint.id,
                    state=s.state,
                    complete_date=s.complete_date,
                )
            ids.append(sprint.id)
        return ids

    # ---------------------------------------------------------------- epics

    async def _create_epics(
        self, project_key: str, epics: list[SeedIssue], now: datetime
    ) -> dict[str, str]:
        """summary -> issue_key, para resolver epic_summary das stories."""
        keys: dict[str, str] = {}
        for e in epics:
            created_at = now + timedelta(days=e.created_offset_days)
            issue = await self.jira.create_issue(
                IssueCreatePayload(
                    project_key=project_key,
                    summary=e.summary,
                    issue_type=e.issue_type,
                    description=e.description,
                    labels=e.labels,
                    created_at=created_at,
                    updated_at=created_at,
                )
            )
            keys[e.summary] = issue.key
        return keys

    # ------------------------------------------------------------- stories

    async def _create_stories(
        self,
        project_key: str,
        stories: list[SeedIssue],
        sprint_ids: list[str],
        epic_keys: dict[str, str],
        now: datetime,
    ) -> int:
        count = 0
        for s in stories:
            created_at = now + timedelta(days=s.created_offset_days)
            sprint_id = sprint_ids[s.sprint_index] if s.sprint_index is not None else None
            epic_key = epic_keys.get(s.epic_summary) if s.epic_summary else None

            resolved_at = None
            last_activity_at = None
            if s.resolved_offset_days is not None:
                resolved_at = now + timedelta(days=s.resolved_offset_days)
                last_activity_at = resolved_at
            else:
                last_activity_at = created_at

            issue = await self.jira.create_issue(
                IssueCreatePayload(
                    project_key=project_key,
                    summary=s.summary,
                    issue_type=s.issue_type,
                    description=s.description,
                    labels=s.labels,
                    assignee_account_id=s.assignee,
                    story_points=s.story_points,
                    sprint_id=sprint_id,
                    epic_key=epic_key,
                    created_at=created_at,
                    updated_at=last_activity_at,
                    status=s.status,
                    story_points_actual=s.story_points_actual,
                    resolved_at=resolved_at,
                )
            )
            # Reforço de timestamps no mock (algumas combinações precisam de update)
            if s.resolved_offset_days is not None:
                await self.jira.update_issue(
                    issue.key,
                    status=IssueStatus.DONE,
                    last_activity_at=resolved_at,
                    resolved_at=resolved_at,
                    story_points_actual=s.story_points_actual,
                )
            count += 1
        return count
