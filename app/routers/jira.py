from fastapi import APIRouter, Query, Request

from app.schemas.jira import Issue, IssueStatus, Sprint

router = APIRouter()


@router.get("/issues/{project_key}", response_model=list[Issue])
async def list_issues(
    request: Request,
    project_key: str,
    sprint_id: str | None = Query(default=None),
    status: IssueStatus | None = Query(default=None),
    max_results: int = Query(default=200, ge=1, le=1000),
) -> list[Issue]:
    """Lista issues do projeto. Suporta filtro por sprint e status."""
    return await request.app.state.jira.search_issues(
        project_key=project_key,
        sprint_id=sprint_id,
        status=status,
        max_results=max_results,
    )


@router.get("/sprints/{project_key}", response_model=list[Sprint])
async def list_sprints(request: Request, project_key: str) -> list[Sprint]:
    """Lista sprints do projeto. (No REST cliente da Etapa 1, retorna vazio
    — sprint listing via Agile API entra em etapa futura)."""
    return await request.app.state.jira.list_sprints(project_key)
