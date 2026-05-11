"""Posta comentários das recomendações via MCP.

Pega recomendações status='proposed' que ainda não foram postadas
(jira_comment_id NULL), escolhe a issue alvo e chama
mcp.add_comment(). Persiste o comment_id de volta — esse é o anchor
que a etapa de read-feedback (3c+) vai usar para ler respostas.
"""

from datetime import datetime, timezone

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.jira_mcp import JiraMCPClient, MCPClientError
from app.core.logging import get_logger
from app.db.models import ProjectRow, RecommendationRow

log = get_logger(__name__)


class PostResult(BaseModel):
    recommendation_id: int
    target_key: str | None
    status: str  # "posted" | "skipped_no_target" | "error"
    jira_comment_id: str | None = None
    error: str | None = None


class PostCommentsStats(BaseModel):
    project_key: str
    candidates: int
    posted: int
    skipped_no_target: int
    errors: int
    results: list[PostResult]


class PostCommentsService:
    def __init__(self, session: AsyncSession, mcp: JiraMCPClient):
        self.session = session
        self.mcp = mcp

    async def post_pending(
        self, project_key: str, limit: int = 200
    ) -> PostCommentsStats:
        proj_id = (
            await self.session.scalars(
                select(ProjectRow.id).where(ProjectRow.key == project_key)
            )
        ).first()
        if proj_id is None:
            return PostCommentsStats(
                project_key=project_key,
                candidates=0,
                posted=0,
                skipped_no_target=0,
                errors=0,
                results=[],
            )

        candidates = (
            await self.session.scalars(
                select(RecommendationRow)
                .where(RecommendationRow.project_id == proj_id)
                .where(RecommendationRow.status == "proposed")
                .where(RecommendationRow.jira_comment_id.is_(None))
                .order_by(RecommendationRow.id)
                .limit(limit)
            )
        ).all()

        results: list[PostResult] = []
        posted = skipped = errors = 0

        for rec in candidates:
            target = pick_target(rec)
            if target is None:
                skipped += 1
                results.append(
                    PostResult(
                        recommendation_id=rec.id,
                        target_key=None,
                        status="skipped_no_target",
                    )
                )
                continue

            try:
                comment = await self.mcp.add_comment(target, rec.comment_body)
                rec.jira_comment_id = str(comment["id"])
                rec.updated_at = datetime.now(timezone.utc)
                posted += 1
                results.append(
                    PostResult(
                        recommendation_id=rec.id,
                        target_key=target,
                        status="posted",
                        jira_comment_id=rec.jira_comment_id,
                    )
                )
            except MCPClientError as e:
                errors += 1
                log.warning(
                    "post_comment_failed", rec_id=rec.id, target=target, error=str(e)
                )
                results.append(
                    PostResult(
                        recommendation_id=rec.id,
                        target_key=target,
                        status="error",
                        error=str(e),
                    )
                )

        await self.session.flush()
        log.info(
            "post_comments_complete",
            project_key=project_key,
            candidates=len(candidates),
            posted=posted,
            skipped=skipped,
            errors=errors,
        )
        return PostCommentsStats(
            project_key=project_key,
            candidates=len(candidates),
            posted=posted,
            skipped_no_target=skipped,
            errors=errors,
            results=results,
        )


def pick_target(rec: RecommendationRow) -> str | None:
    """Função pública: escolhe a issue alvo de uma recomendação.

    Reusada pelo follow-up de feedback (mesmo target da postagem
    original — o comentário fica no thread certo).

    Regras:
    - Sem target_keys (ex.: standalone carryover_warning): pula. Esse vai
      pra dashboard, não vira comment no Jira.
    - dedup: posta na issue mais nova (lexicograficamente maior — convenção
      SSD-N onde N maior = criada depois). Preserva discussão da mais antiga.
    - Demais: posta na primeira (single-target).
    """
    keys = list(rec.target_keys or [])
    if not keys:
        return None
    if rec.type == "dedup" and len(keys) >= 2:
        return max(keys, key=_sort_key_for_issue)
    return keys[0]


def _sort_key_for_issue(key: str) -> int:
    """SSD-25 → 25, para ordenar por número da issue."""
    try:
        return int(key.split("-")[-1])
    except (ValueError, IndexError):
        return 0
