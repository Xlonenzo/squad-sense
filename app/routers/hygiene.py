from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.session import get_session
from app.services.hygiene.models import HygieneReport
from app.services.hygiene.service import HygieneService

router = APIRouter()


@router.post("/run", response_model=HygieneReport)
async def run_hygiene(
    project_key: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> HygieneReport:
    """Roda os 4 detectores algorítmicos (dedup, obsolescência, DoR,
    epic emergente) e devolve as findings ordenadas por severidade.

    Pré-requisito: /ingest/run executado antes (precisa de embeddings).
    """
    pk = project_key or settings.jira_project_key
    return await HygieneService(session).run(pk)
