from app.clients.jira_client import JiraClient
from app.config import settings
from app.core.exceptions import BootstrapError, JiraClientError
from app.core.logging import get_logger
from app.schemas.bootstrap import BootstrapProjectResponse

log = get_logger(__name__)


class BootstrapService:
    def __init__(self, jira: JiraClient):
        self.jira = jira

    async def create_project(self) -> BootstrapProjectResponse:
        key = settings.jira_project_key
        name = settings.jira_project_name

        existing = await self.jira.get_project(key)
        if existing is not None:
            log.info("bootstrap_project_exists", key=key, mode=self.jira.mode)
            return BootstrapProjectResponse(
                project_key=existing.key,
                project_id=existing.id,
                project_name=existing.name,
                created=False,
                mode=self.jira.mode,
            )

        try:
            project = await self.jira.create_project(key=key, name=name)
        except JiraClientError as e:
            raise BootstrapError(f"falha ao criar projeto: {e.message}") from e

        log.info("bootstrap_project_created", key=key, mode=self.jira.mode)
        return BootstrapProjectResponse(
            project_key=project.key,
            project_id=project.id,
            project_name=project.name,
            created=True,
            mode=self.jira.mode,
        )
