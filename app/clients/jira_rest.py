"""JiraRestClient — cliente para Jira Cloud real (httpx + Basic Auth).

Implementa o subconjunto da Jira Platform REST API v3 que a Etapa 1
precisa: get_myself, get/create_project, create/search_issues.

Limitações conhecidas (deliberadas para o escopo da Etapa 1):
- Sprints exigem a Agile REST API + board_id (cada projeto Scrum
  team-managed cria um board automaticamente). Não implementado aqui;
  o seed sintético com sprints históricos roda apenas em mock mode.
- created_at / updated_at retroativos não são suportados pela API
  pública do Jira Cloud — outra razão para o seed longitudinal viver
  no mock.
- Story Points é custom field; o ID varia por instância. Configurável
  via env (JIRA_STORY_POINTS_FIELD, default customfield_10016).
"""

import os
from datetime import datetime
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import settings
from app.core.exceptions import JiraAuthError, JiraClientError
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

STORY_POINTS_FIELD = os.getenv("JIRA_STORY_POINTS_FIELD", "customfield_10016")
SCRUM_TEMPLATE = "com.pyxis.greenhopper.jira:gh-simplified-scrum-classic"


def _adf(text: str | None) -> dict[str, Any] | None:
    """Embrulha texto plano em Atlassian Document Format (mínimo)."""
    if not text:
        return None
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": text}]}
        ],
    }


def _adf_to_text(adf: Any) -> str | None:
    """Extrai texto de uma estrutura ADF (best-effort)."""
    if not adf or not isinstance(adf, dict):
        return None
    parts: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "text" and "text" in node:
                parts.append(node["text"])
            for child in node.get("content", []) or []:
                walk(child)

    walk(adf)
    return " ".join(parts) if parts else None


class JiraRestClient:
    mode = "rest"

    def __init__(self) -> None:
        if not settings.jira_credentials_present:
            raise JiraAuthError(
                "Credenciais do Jira ausentes. Defina JIRA_BASE_URL/JIRA_EMAIL/"
                "JIRA_API_TOKEN ou rode com JIRA_MOCK=true."
            )

        self.base_url = settings.jira_base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            auth=(settings.jira_email, settings.jira_api_token),
            timeout=httpx.Timeout(30.0, connect=10.0),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )

    # ----------------------------------------------------------- HTTP helper

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        retry=retry_if_exception_type(httpx.TransportError),
        reraise=True,
    )
    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = f"{self.base_url}{path}"
        try:
            resp = await self._client.request(method, url, **kwargs)
        except httpx.TransportError as e:
            log.warning("jira_transport_error", method=method, path=path, error=str(e))
            raise

        if resp.status_code in (401, 403):
            raise JiraAuthError(
                f"Jira retornou {resp.status_code} para {method} {path}: {resp.text[:200]}"
            )
        if resp.status_code >= 400:
            raise JiraClientError(
                f"Jira {resp.status_code} em {method} {path}: {resp.text[:300]}"
            )
        if not resp.content:
            return {}
        return resp.json()

    # ----------------------------------------------------------------- users

    async def get_myself(self) -> User:
        data = await self._request("GET", "/rest/api/3/myself")
        return User(
            account_id=data["accountId"],
            display_name=data.get("displayName", ""),
            email_address=data.get("emailAddress"),
        )

    # -------------------------------------------------------------- projects

    async def get_project(self, key: str) -> Project | None:
        try:
            data = await self._request("GET", f"/rest/api/3/project/{key}")
        except JiraClientError as e:
            if "404" in str(e):
                return None
            raise
        return Project(
            id=str(data["id"]),
            key=data["key"],
            name=data["name"],
            lead=User(
                account_id=data.get("lead", {}).get("accountId", ""),
                display_name=data.get("lead", {}).get("displayName", ""),
            )
            if data.get("lead")
            else None,
        )

    async def create_project(
        self,
        key: str,
        name: str,
        lead_account_id: str | None = None,
    ) -> Project:
        if lead_account_id is None:
            me = await self.get_myself()
            lead_account_id = me.account_id

        payload = {
            "key": key,
            "name": name,
            "projectTypeKey": "software",
            "projectTemplateKey": SCRUM_TEMPLATE,
            "leadAccountId": lead_account_id,
            "assigneeType": "PROJECT_LEAD",
        }
        data = await self._request("POST", "/rest/api/3/project", json=payload)
        log.info("jira_project_created", key=key, id=data.get("id"))
        return Project(
            id=str(data["id"]),
            key=data["key"],
            name=name,
            lead=User(account_id=lead_account_id, display_name=""),
        )

    # --------------------------------------------------------------- issues

    async def create_issue(self, payload: IssueCreatePayload) -> Issue:
        fields: dict[str, Any] = {
            "project": {"key": payload.project_key},
            "summary": payload.summary,
            "issuetype": {"name": payload.issue_type.value},
        }
        if payload.description:
            fields["description"] = _adf(payload.description)
        if payload.labels:
            fields["labels"] = payload.labels
        if payload.assignee_account_id:
            fields["assignee"] = {"accountId": payload.assignee_account_id}
        if payload.story_points is not None:
            fields[STORY_POINTS_FIELD] = payload.story_points

        data = await self._request("POST", "/rest/api/3/issue", json={"fields": fields})
        # POST /issue só devolve {id, key, self}; precisamos buscar para shape completo
        return await self._get_issue(data["key"])

    async def _get_issue(self, key: str) -> Issue:
        data = await self._request(
            "GET",
            f"/rest/api/3/issue/{key}",
            params={"fields": f"*all,{STORY_POINTS_FIELD}"},
        )
        return self._parse_issue(data)

    async def search_issues(
        self,
        project_key: str,
        *,
        sprint_id: str | None = None,
        status: IssueStatus | None = None,
        max_results: int = 200,
    ) -> list[Issue]:
        clauses = [f'project = "{project_key}"']
        if status is not None:
            clauses.append(f'status = "{status.value}"')
        if sprint_id is not None:
            clauses.append(f'sprint = {sprint_id}')
        jql = " AND ".join(clauses)

        params = {
            "jql": jql,
            "maxResults": max_results,
            "fields": f"summary,description,issuetype,status,labels,components,"
            f"assignee,reporter,created,updated,resolutiondate,parent,"
            f"{STORY_POINTS_FIELD}",
        }
        data = await self._request("GET", "/rest/api/3/search/jql", params=params)
        return [self._parse_issue(raw) for raw in data.get("issues", [])]

    # -------------------------------- operações deferidas para etapas futuras

    async def list_sprints(self, project_key: str) -> list[Sprint]:
        # Requer Agile API + board_id. Implementado em etapa futura.
        return []

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
        raise JiraClientError(
            "Sprints históricas exigem Agile API + timestamps retroativos. "
            "Use JIRA_MOCK=true para o seed sintético longitudinal.",
            code="rest_sprint_unsupported",
        )

    async def update_sprint_state(
        self,
        sprint_id: str,
        state: SprintState,
        complete_date: datetime | None = None,
    ) -> Sprint:
        raise JiraClientError(
            "Operação de sprint não implementada no REST cliente da Etapa 1.",
            code="rest_sprint_unsupported",
        )

    async def update_issue(
        self,
        key: str,
        *,
        status: IssueStatus | None = None,
        story_points_actual: float | None = None,
        resolved_at: datetime | None = None,
        last_activity_at: datetime | None = None,
    ) -> Issue:
        # Update parcial via PUT /issue/{key}; transição de status precisa do
        # endpoint /transitions. Mantido fora da Etapa 1 — o agente da etapa 3
        # vai precisar disso e a gente implementa lá com o caso de uso na mão.
        raise JiraClientError(
            "update_issue ainda não implementado no REST cliente.",
            code="rest_update_unsupported",
        )

    # ------------------------------------------------------------- comments

    async def add_comment(self, issue_key: str, body: str) -> JiraComment:
        payload = {"body": _adf(body)}
        data = await self._request(
            "POST", f"/rest/api/3/issue/{issue_key}/comment", json=payload
        )
        return self._parse_comment(data, issue_key)

    async def list_comments(self, issue_key: str) -> list[JiraComment]:
        data = await self._request(
            "GET", f"/rest/api/3/issue/{issue_key}/comment", params={"maxResults": 100}
        )
        return [self._parse_comment(c, issue_key) for c in data.get("comments", [])]

    def _parse_comment(self, raw: dict[str, Any], issue_key: str) -> JiraComment:
        author = User(
            account_id=(raw.get("author") or {}).get("accountId", ""),
            display_name=(raw.get("author") or {}).get("displayName", ""),
            email_address=(raw.get("author") or {}).get("emailAddress"),
        )
        return JiraComment(
            id=str(raw["id"]),
            issue_key=issue_key,
            body=_adf_to_text(raw.get("body")) or "",
            author=author,
            created_at=_parse_dt(raw.get("created")),
        )

    async def close(self) -> None:
        await self._client.aclose()

    # --------------------------------------------------------------- parsing

    def _parse_issue(self, raw: dict[str, Any]) -> Issue:
        f = raw.get("fields", {})
        assignee = None
        if a := f.get("assignee"):
            assignee = User(
                account_id=a.get("accountId", ""),
                display_name=a.get("displayName", ""),
                email_address=a.get("emailAddress"),
            )
        reporter = None
        if r := f.get("reporter"):
            reporter = User(
                account_id=r.get("accountId", ""),
                display_name=r.get("displayName", ""),
                email_address=r.get("emailAddress"),
            )

        try:
            issue_type = IssueType(f.get("issuetype", {}).get("name", "Task"))
        except ValueError:
            issue_type = IssueType.TASK

        try:
            status = IssueStatus(f.get("status", {}).get("name", "To Do"))
        except ValueError:
            status = IssueStatus.TODO

        return Issue(
            id=str(raw["id"]),
            key=raw["key"],
            project_key=raw["key"].split("-")[0],
            summary=f.get("summary", ""),
            description=_adf_to_text(f.get("description")),
            issue_type=issue_type,
            status=status,
            labels=list(f.get("labels", []) or []),
            components=[c.get("name") for c in (f.get("components") or []) if c.get("name")],
            assignee=assignee,
            reporter=reporter,
            story_points_estimated=f.get(STORY_POINTS_FIELD),
            story_points_actual=None,  # actual não é nativo do Jira; agente vai inferir
            sprint_id=None,
            epic_key=(f.get("parent") or {}).get("key"),
            created_at=_parse_dt(f.get("created")),
            updated_at=_parse_dt(f.get("updated")),
            last_activity_at=_parse_dt(f.get("updated")),
            resolved_at=_parse_dt(f.get("resolutiondate")),
        )


def _parse_dt(value: str | None) -> datetime:
    if not value:
        return datetime.now()
    # Jira timestamps: "2024-12-01T10:30:00.000+0000"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
