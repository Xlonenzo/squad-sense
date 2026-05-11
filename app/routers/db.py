from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import IssueEmbeddingRow, IssueRow, ProjectRow
from app.db.session import get_session
from app.schemas.db import DbIssueOut, SimilarHit

router = APIRouter()


@router.get("/issues", response_model=list[DbIssueOut])
async def list_issues_db(
    project_key: str | None = Query(default=None),
    has_embedding: bool | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    session: AsyncSession = Depends(get_session),
) -> list[DbIssueOut]:
    """Lista issues do DB (não bate no Jira). Útil para inspecionar o
    estado pós-ingestion e filtrar por presença de embedding."""
    stmt = (
        select(IssueRow, ProjectRow)
        .join(ProjectRow, IssueRow.project_id == ProjectRow.id)
        .options(selectinload(IssueRow.embedding))
        .order_by(IssueRow.id)
        .limit(limit)
    )
    if project_key:
        stmt = stmt.where(ProjectRow.key == project_key)

    rows = (await session.execute(stmt)).all()
    out: list[DbIssueOut] = []
    for issue, project in rows:
        has_emb = issue.embedding is not None
        if has_embedding is not None and has_emb != has_embedding:
            continue
        out.append(
            DbIssueOut(
                id=issue.id,
                key=issue.key,
                project_key=project.key,
                summary=issue.summary,
                issue_type=issue.issue_type,
                status=issue.status,
                labels=list(issue.labels or []),
                assignee=issue.assignee_display_name,
                story_points_estimated=issue.story_points_estimated,
                sprint_id=issue.sprint_id,
                epic_key=issue.epic_key,
                created_at=issue.created_at,
                has_embedding=has_emb,
            )
        )
    return out


@router.get("/issues/{issue_key}/similar", response_model=list[SimilarHit])
async def similar_issues(
    issue_key: str,
    k: int = Query(default=5, ge=1, le=50),
    session: AsyncSession = Depends(get_session),
) -> list[SimilarHit]:
    """Top-k issues semanticamente próximas a `issue_key`, por cosine.

    Foundation do dedup do Hygiene Pass — é com este sinal que o agente
    da Etapa 3 decide se duas issues são candidatas a duplicata.
    """
    target = (
        await session.scalars(
            select(IssueRow)
            .where(IssueRow.key == issue_key)
            .options(selectinload(IssueRow.embedding))
        )
    ).first()
    if target is None:
        raise HTTPException(404, f"issue {issue_key} não encontrada")
    if target.embedding is None:
        raise HTTPException(
            409,
            f"issue {issue_key} ainda não tem embedding — rode /ingest/run primeiro",
        )

    target_vec = target.embedding.embedding

    # IVFFlat com lists=100 numa tabela pequena requer probes alto
    # para varrer todas as células. Com k=50 o teto, isso é seguro.
    await session.execute(text("SET LOCAL ivfflat.probes = 100"))

    # cosine_distance() é exposto pelo pgvector.sqlalchemy
    distance = IssueEmbeddingRow.embedding.cosine_distance(target_vec).label("distance")
    stmt = (
        select(IssueRow, distance)
        .join(IssueEmbeddingRow, IssueEmbeddingRow.issue_id == IssueRow.id)
        .where(IssueRow.id != target.id)
        .order_by(distance)
        .limit(k)
    )
    rows = (await session.execute(stmt)).all()

    return [
        SimilarHit(
            key=issue.key,
            summary=issue.summary,
            issue_type=issue.issue_type,
            status=issue.status,
            labels=list(issue.labels or []),
            distance=float(dist),
            similarity=float(1.0 - dist),
        )
        for issue, dist in rows
    ]
