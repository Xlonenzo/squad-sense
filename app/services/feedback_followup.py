"""Follow-up no Jira via MCP após aceitar/rejeitar uma recomendação.

Fecha o closed loop visualmente no Jira: quando o time aceita ou rejeita
uma recomendação no dashboard, o agente posta um comentário de
acompanhamento na mesma issue, indicando a decisão e o feedback humano
opcional. Sinal explícito de que o squad respondeu.

Best-effort: se o MCP falhar, não derruba a operação principal de
feedback (o status no Postgres já foi salvo).
"""

from app.clients.jira_mcp import JiraMCPClient
from app.core.logging import get_logger
from app.db.models import RecommendationRow
from app.services.post_comments_service import pick_target

log = get_logger(__name__)


def _accept_body(rec: RecommendationRow) -> str:
    body = (
        "✅ **Squad Sense — recomendação aceita**\n\n"
        "O time aceitou esta recomendação. Esse sinal entra na "
        "calibração do agente para futuras runs."
    )
    if rec.human_feedback:
        body += f"\n\n> {rec.human_feedback}"
    return body


def _reject_body(rec: RecommendationRow) -> str:
    body = (
        f"❌ **Squad Sense — recomendação rejeitada** (`ss-skip {rec.type}`)\n\n"
        "O time decidiu não seguir esta recomendação. O agente vai "
        "suprimir sugestões similares para este squad em runs futuros."
    )
    if rec.human_feedback:
        body += f"\n\n> {rec.human_feedback}"
    return body


def build_followup_body(rec: RecommendationRow) -> str | None:
    if rec.status == "accepted":
        return _accept_body(rec)
    if rec.status == "rejected":
        return _reject_body(rec)
    return None


async def post_followup(rec: RecommendationRow) -> str | None:
    """Posta o follow-up via MCP. Devolve o comment_id do follow-up ou
    None se não for possível (sem target ou status incorreto)."""
    target = pick_target(rec)
    if target is None:
        log.info("feedback_followup_skipped_no_target", rec_id=rec.id)
        return None

    body = build_followup_body(rec)
    if body is None:
        return None

    async with JiraMCPClient() as mcp:
        comment = await mcp.add_comment(target, body)

    follow_up_id = str(comment["id"])
    log.info(
        "feedback_followup_posted",
        rec_id=rec.id,
        target=target,
        follow_up_id=follow_up_id,
    )
    return follow_up_id
