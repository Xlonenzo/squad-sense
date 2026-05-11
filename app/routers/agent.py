from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agent.coach import CoachAgent, CoachRunStats
from app.clients.jira_mcp import JiraMCPClient, MCPClientError
from app.config import settings
from app.core.logging import get_logger
from app.db.models import IssueEmbeddingRow, IssueRow, RecommendationRow
from app.db.session import get_session
from app.schemas.rag_inspector import (
    EvidenceIssue,
    RagInspectorOut,
    TargetVectorRetrieval,
    VectorNeighbor,
)
from app.schemas.recommendation import RecommendationFeedbackIn, RecommendationOut
from app.services.feedback_followup import post_followup
from app.services.post_comments_service import PostCommentsService, PostCommentsStats

log = get_logger(__name__)

router = APIRouter()


@router.post("/run", response_model=CoachRunStats)
async def run_agent(
    request: Request,
    project_key: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> CoachRunStats:
    """Executa o pipeline coach completo: hygiene → mining → cross-ref →
    síntese (LLM com RAG) → persiste recommendations com status='proposed'.
    """
    agent = CoachAgent(session=session, llm=request.app.state.llm)
    return await agent.run(project_key or settings.jira_project_key)


@router.post("/post-comments", response_model=PostCommentsStats)
async def post_comments(
    project_key: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> PostCommentsStats:
    """Posta as recommendations 'proposed' (que ainda não foram entregues)
    como comentários no Jira via MCP. Spawna o servidor MCP local como
    subprocess; trocá-lo pelo mcp-atlassian é mudar 1 linha no JiraMCPClient.
    """
    pk = project_key or settings.jira_project_key
    async with JiraMCPClient() as mcp:
        service = PostCommentsService(session=session, mcp=mcp)
        return await service.post_pending(pk)


@router.get("/recommendations", response_model=list[RecommendationOut])
async def list_recommendations(
    project_key: str | None = Query(default=None),
    status: str | None = Query(default=None),
    rec_type: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    session: AsyncSession = Depends(get_session),
) -> list[RecommendationOut]:
    """Lista recommendations já geradas, filtrando opcionalmente por
    status (proposed/accepted/rejected) ou tipo."""
    from app.db.models import ProjectRow

    stmt = (
        select(RecommendationRow)
        .order_by(RecommendationRow.id.desc())
        .limit(limit)
    )
    if project_key:
        proj_stmt = select(ProjectRow.id).where(ProjectRow.key == project_key)
        proj_id = (await session.scalars(proj_stmt)).first()
        if proj_id is None:
            return []
        stmt = stmt.where(RecommendationRow.project_id == proj_id)
    if status:
        stmt = stmt.where(RecommendationRow.status == status)
    if rec_type:
        stmt = stmt.where(RecommendationRow.type == rec_type)

    rows = (await session.scalars(stmt)).all()
    return [
        RecommendationOut(
            id=r.id,
            type=r.type,
            status=r.status,
            severity=r.severity,
            confidence=r.confidence,
            target_keys=list(r.target_keys or []),
            summary=r.summary,
            comment_body=r.comment_body,
            evidence=dict(r.evidence or {}),
            evidence_issue_keys=list(r.evidence_issue_keys or []),
            model_used=r.model_used,
            human_feedback=r.human_feedback,
            jira_comment_id=r.jira_comment_id,
            created_at=r.created_at,
            updated_at=r.updated_at,
        )
        for r in rows
    ]


@router.post("/recommendations/{rec_id}/feedback", response_model=RecommendationOut)
async def feedback(
    rec_id: int,
    body: RecommendationFeedbackIn,
    session: AsyncSession = Depends(get_session),
) -> RecommendationOut:
    """Closed loop: time aceita ou rejeita uma recomendação. Esse sinal
    é o que treina o agente para esse time específico ao longo do tempo."""
    if body.status not in ("accepted", "rejected"):
        raise HTTPException(400, "status deve ser 'accepted' ou 'rejected'")
    rec = (
        await session.scalars(
            select(RecommendationRow).where(RecommendationRow.id == rec_id)
        )
    ).first()
    if rec is None:
        raise HTTPException(404, f"recommendation {rec_id} não existe")
    rec.status = body.status
    rec.human_feedback = body.human_feedback
    rec.updated_at = datetime.now(timezone.utc)
    await session.flush()

    # Closed loop visível: se a rec original já foi postada no Jira,
    # posta um follow-up dizendo que o time aceitou/rejeitou. MCP
    # best-effort — falha não derruba o feedback (status já salvo).
    if rec.jira_comment_id:
        try:
            await post_followup(rec)
        except MCPClientError as e:
            log.warning(
                "feedback_followup_failed", rec_id=rec.id, error=str(e)
            )
        except Exception as e:
            log.exception("feedback_followup_unexpected", rec_id=rec.id)
            _ = e  # silencia warning de var não usada

    return RecommendationOut(
        id=rec.id,
        type=rec.type,
        status=rec.status,
        severity=rec.severity,
        confidence=rec.confidence,
        target_keys=list(rec.target_keys or []),
        summary=rec.summary,
        comment_body=rec.comment_body,
        evidence=dict(rec.evidence or {}),
        evidence_issue_keys=list(rec.evidence_issue_keys or []),
        model_used=rec.model_used,
        human_feedback=rec.human_feedback,
        jira_comment_id=rec.jira_comment_id,
        created_at=rec.created_at,
        updated_at=rec.updated_at,
    )


@router.get("/recommendations/{rec_id}/rag", response_model=RagInspectorOut)
async def rag_inspector(
    rec_id: int,
    session: AsyncSession = Depends(get_session),
) -> RagInspectorOut:
    """Mostra os dois mecanismos de RAG por trás da recomendação:

    1. **Vector retrieval** — top-K vizinhos por cosseno (pgvector) para
       cada target_key. É o que sustenta o detector de dedup e o
       cluster que ativou cross-refs.
    2. **Evidence loading** — texto completo das issues citadas como
       evidência (evidence_issue_keys), tal como foi entregue ao LLM
       no `evidence_issues_full` do user prompt.

    Endpoint pensado para o RAG Inspector da UI: prova visualmente que
    o LLM citou apenas o que estava no contexto retrieved.
    """
    rec = (
        await session.scalars(
            select(RecommendationRow).where(RecommendationRow.id == rec_id)
        )
    ).first()
    if rec is None:
        raise HTTPException(404, f"recommendation {rec_id} não existe")

    # 1) Vector retrieval — para cada target_key, top-5 por cosseno
    vector_retrieval: list[TargetVectorRetrieval] = []
    if rec.target_keys:
        await session.execute(text("SET LOCAL ivfflat.probes = 100"))

    for target_key in rec.target_keys:
        target = (
            await session.scalars(
                select(IssueRow)
                .where(IssueRow.key == target_key)
                .options(selectinload(IssueRow.embedding))
            )
        ).first()
        if target is None or target.embedding is None:
            continue

        target_vec = target.embedding.embedding
        distance = IssueEmbeddingRow.embedding.cosine_distance(target_vec).label(
            "distance"
        )
        stmt = (
            select(IssueRow, distance)
            .join(IssueEmbeddingRow, IssueEmbeddingRow.issue_id == IssueRow.id)
            .where(IssueRow.id != target.id)
            .order_by(distance)
            .limit(5)
        )
        rows = (await session.execute(stmt)).all()

        vector_retrieval.append(
            TargetVectorRetrieval(
                target_key=target_key,
                neighbors=[
                    VectorNeighbor(
                        key=issue.key,
                        summary=issue.summary,
                        labels=list(issue.labels or []),
                        assignee=issue.assignee_display_name,
                        status=issue.status,
                        distance=round(float(dist), 4),
                        similarity=round(float(1.0 - dist), 4),
                    )
                    for issue, dist in rows
                ],
            )
        )

    # 2) Evidence loading — texto completo dos evidence_issue_keys
    evidence_loaded: list[EvidenceIssue] = []
    if rec.evidence_issue_keys:
        evidence_rows = (
            await session.scalars(
                select(IssueRow).where(IssueRow.key.in_(list(rec.evidence_issue_keys)))
            )
        ).all()
        # Manter a ordem original dos evidence_issue_keys
        by_key = {row.key: row for row in evidence_rows}
        for key in rec.evidence_issue_keys:
            issue = by_key.get(key)
            if issue is None:
                continue
            est = issue.story_points_estimated
            actual = issue.story_points_actual
            ratio = (actual / est) if (est and actual and est > 0) else None
            evidence_loaded.append(
                EvidenceIssue(
                    key=issue.key,
                    summary=issue.summary,
                    status=issue.status,
                    labels=list(issue.labels or []),
                    assignee=issue.assignee_display_name,
                    story_points_estimated=est,
                    story_points_actual=actual,
                    ratio=round(ratio, 3) if ratio else None,
                )
            )

    notes: list[str] = []
    if vector_retrieval:
        notes.append(
            "Vector retrieval via pgvector cosine_distance + IVFFlat index. "
            "Embeddings text-embedding-3-small (1536 dims)."
        )
    if evidence_loaded:
        notes.append(
            "Evidence loading injeta o texto destas issues no user prompt do LLM "
            "como evidence_issues_full. System prompt proíbe inventar keys — "
            "as citadas no comentário vêm desta lista."
        )
    if not vector_retrieval and not evidence_loaded:
        notes.append(
            "Esta recomendação não usou retrieval vectorial nem evidence loading "
            "(ex.: alerta squad-level sem target específico)."
        )

    return RagInspectorOut(
        recommendation_id=rec.id,
        target_keys=list(rec.target_keys or []),
        evidence_issue_keys=list(rec.evidence_issue_keys or []),
        model_used=rec.model_used,
        vector_retrieval=vector_retrieval,
        evidence_issues_loaded=evidence_loaded,
        notes=notes,
    )
