from fastapi import APIRouter, Request

from app.schemas.bootstrap import BootstrapProjectResponse, BootstrapSeedResponse
from app.services.bootstrap_service import BootstrapService
from app.services.seed_service import SeedService

router = APIRouter()


@router.post("/project", response_model=BootstrapProjectResponse)
async def bootstrap_project(request: Request) -> BootstrapProjectResponse:
    """Cria o projeto Scrum no Jira (idempotente: retorna o existente se já houver)."""
    service = BootstrapService(request.app.state.jira)
    return await service.create_project()


@router.post("/seed", response_model=BootstrapSeedResponse)
async def bootstrap_seed(request: Request) -> BootstrapSeedResponse:
    """Popula 6 sprints históricas + ~50 issues com padrões plantados.

    Exige JIRA_MOCK=true (timestamps retroativos não são suportados pelo
    Jira Cloud). Para o uso em produção, use o ingestion job (Etapa 2)
    contra dados que já existem no Jira real.
    """
    service = SeedService(request.app.state.jira)
    return await service.seed()
