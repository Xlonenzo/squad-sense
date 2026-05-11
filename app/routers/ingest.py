from fastapi import APIRouter, Depends, Request

from app.db.session import get_session
from app.services.ingestion_service import IngestionService, IngestionStats
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


@router.post("/run", response_model=IngestionStats)
async def run_ingestion(
    request: Request,
    project_key: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> IngestionStats:
    """Sincroniza JiraClient → DB e recomputa embeddings das issues alteradas.

    Idempotente. Retorna estatísticas (issues processadas, embeddings
    computados vs. pulados por inalterados, model usado).
    """
    service = IngestionService(
        session=session,
        jira=request.app.state.jira,
        embedder=request.app.state.embedder,
    )
    return await service.run(project_key=project_key)
