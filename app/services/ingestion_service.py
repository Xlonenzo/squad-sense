"""IngestionService — sincroniza JiraClient → DB + recomputa embeddings.

Idempotente: pode ser chamado N vezes sem duplicar dados. Recomputa
embedding apenas se o text_hash da issue mudou desde o último run.
"""

from collections.abc import Iterable
from datetime import datetime, timezone

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.embeddings import (
    EmbeddingClient,
    issue_text_for_embedding,
    text_hash,
)
from app.clients.jira_client import JiraClient
from app.config import settings
from app.core.exceptions import BootstrapError
from app.core.logging import get_logger
from app.db.models import IssueEmbeddingRow, IssueRow, ProjectRow, SprintRow
from app.schemas.jira import Issue as IssueSchema
from app.schemas.jira import Sprint as SprintSchema

log = get_logger(__name__)


class IngestionStats(BaseModel):
    project_key: str
    projects_upserted: int
    sprints_upserted: int
    issues_upserted: int
    embeddings_computed: int
    embeddings_skipped_unchanged: int
    embedding_model: str


class IngestionService:
    def __init__(
        self,
        session: AsyncSession,
        jira: JiraClient,
        embedder: EmbeddingClient,
    ):
        self.session = session
        self.jira = jira
        self.embedder = embedder

    async def run(self, project_key: str | None = None) -> IngestionStats:
        project_key = project_key or settings.jira_project_key

        project = await self.jira.get_project(project_key)
        if project is None:
            raise BootstrapError(
                f"projeto {project_key} não existe no Jira — rode /bootstrap/project antes."
            )

        sprints = await self.jira.list_sprints(project_key)
        issues = await self.jira.search_issues(project_key, max_results=1000)

        project_row = await self._upsert_project(project.id, project.key, project.name)
        sprint_map = await self._upsert_sprints(sprints, project_row.id)
        upserted_issues, to_embed = await self._upsert_issues(
            issues, project_row.id, sprint_map
        )
        computed = await self._compute_embeddings(to_embed)

        await self.session.flush()

        log.info(
            "ingestion_complete",
            project_key=project_key,
            projects=1,
            sprints=len(sprints),
            issues=upserted_issues,
            embeddings_computed=computed,
            embeddings_skipped=upserted_issues - computed,
        )

        return IngestionStats(
            project_key=project_key,
            projects_upserted=1,
            sprints_upserted=len(sprints),
            issues_upserted=upserted_issues,
            embeddings_computed=computed,
            embeddings_skipped_unchanged=upserted_issues - computed,
            embedding_model=self.embedder.model,
        )

    # --------------------------------------------------------------- project

    async def _upsert_project(self, jira_id: str, key: str, name: str) -> ProjectRow:
        row = (
            await self.session.scalars(
                select(ProjectRow).where(ProjectRow.jira_id == jira_id)
            )
        ).first()
        if row is None:
            row = ProjectRow(
                jira_id=jira_id, key=key, name=name, created_at=_now()
            )
            self.session.add(row)
            await self.session.flush()
        else:
            row.name = name
        return row

    # ---------------------------------------------------------------- sprint

    async def _upsert_sprints(
        self, sprints: Iterable[SprintSchema], project_id: int
    ) -> dict[str, int]:
        """Retorna mapa jira_sprint_id → db sprint_id."""
        result: dict[str, int] = {}
        for s in sprints:
            row = (
                await self.session.scalars(
                    select(SprintRow).where(SprintRow.jira_id == s.id)
                )
            ).first()
            if row is None:
                row = SprintRow(
                    jira_id=s.id,
                    project_id=project_id,
                    name=s.name,
                    state=s.state.value,
                    goal=s.goal,
                    start_date=s.start_date,
                    end_date=s.end_date,
                    complete_date=s.complete_date,
                )
                self.session.add(row)
                await self.session.flush()
            else:
                row.name = s.name
                row.state = s.state.value
                row.goal = s.goal
                row.start_date = s.start_date
                row.end_date = s.end_date
                row.complete_date = s.complete_date
            result[s.id] = row.id
        return result

    # ---------------------------------------------------------------- issues

    async def _upsert_issues(
        self,
        issues: Iterable[IssueSchema],
        project_id: int,
        sprint_map: dict[str, int],
    ) -> tuple[int, list[tuple[IssueRow, str, str]]]:
        """Upsert issues. Devolve (n_upserted, lista_para_embedar).

        lista_para_embedar contém (row, text, hash) só das issues cujo
        text_hash mudou (ou que ainda não têm embedding salvo).
        """
        to_embed: list[tuple[IssueRow, str, str]] = []
        count = 0

        for i in issues:
            text = issue_text_for_embedding(i.summary, i.description)
            new_hash = text_hash(text)

            row = (
                await self.session.scalars(
                    select(IssueRow).where(IssueRow.jira_id == i.id)
                )
            ).first()

            sprint_db_id = sprint_map.get(i.sprint_id) if i.sprint_id else None

            if row is None:
                row = IssueRow(
                    jira_id=i.id,
                    key=i.key,
                    project_id=project_id,
                    sprint_id=sprint_db_id,
                    epic_key=i.epic_key,
                    summary=i.summary,
                    description=i.description,
                    issue_type=i.issue_type.value,
                    status=i.status.value,
                    labels=list(i.labels),
                    components=list(i.components),
                    assignee_account_id=(i.assignee.account_id if i.assignee else None),
                    assignee_display_name=(i.assignee.display_name if i.assignee else None),
                    reporter_account_id=(i.reporter.account_id if i.reporter else None),
                    story_points_estimated=i.story_points_estimated,
                    story_points_actual=i.story_points_actual,
                    created_at=i.created_at,
                    updated_at=i.updated_at,
                    last_activity_at=i.last_activity_at,
                    resolved_at=i.resolved_at,
                    text_hash=new_hash,
                )
                self.session.add(row)
                await self.session.flush()
                to_embed.append((row, text, new_hash))
            else:
                # Atualiza campos mutáveis
                row.key = i.key
                row.project_id = project_id
                row.sprint_id = sprint_db_id
                row.epic_key = i.epic_key
                row.summary = i.summary
                row.description = i.description
                row.issue_type = i.issue_type.value
                row.status = i.status.value
                row.labels = list(i.labels)
                row.components = list(i.components)
                row.assignee_account_id = i.assignee.account_id if i.assignee else None
                row.assignee_display_name = i.assignee.display_name if i.assignee else None
                row.reporter_account_id = i.reporter.account_id if i.reporter else None
                row.story_points_estimated = i.story_points_estimated
                row.story_points_actual = i.story_points_actual
                row.updated_at = i.updated_at
                row.last_activity_at = i.last_activity_at
                row.resolved_at = i.resolved_at

                old_hash = row.text_hash
                row.text_hash = new_hash

                # Decide se precisa reembedar
                emb = (
                    await self.session.scalars(
                        select(IssueEmbeddingRow).where(IssueEmbeddingRow.issue_id == row.id)
                    )
                ).first()
                if emb is None or old_hash != new_hash or emb.model != self.embedder.model:
                    to_embed.append((row, text, new_hash))

            count += 1

        return count, to_embed

    # ----------------------------------------------------------- embeddings

    async def _compute_embeddings(
        self, items: list[tuple[IssueRow, str, str]]
    ) -> int:
        if not items:
            return 0

        texts = [t for _, t, _ in items]
        vectors = await self.embedder.embed(texts)

        for (row, _, h), v in zip(items, vectors, strict=True):
            existing = (
                await self.session.scalars(
                    select(IssueEmbeddingRow).where(IssueEmbeddingRow.issue_id == row.id)
                )
            ).first()
            if existing is None:
                self.session.add(
                    IssueEmbeddingRow(
                        issue_id=row.id,
                        model=self.embedder.model,
                        text_hash=h,
                        embedding=v,
                        created_at=_now(),
                    )
                )
            else:
                existing.model = self.embedder.model
                existing.text_hash = h
                existing.embedding = v
                existing.created_at = _now()

        return len(items)


def _now() -> datetime:
    return datetime.now(timezone.utc)
