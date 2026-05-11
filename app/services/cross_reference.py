"""Cross-reference: cruza issues abertas com Patterns históricos.

Para cada issue aberta, decide se algum Pattern se aplica e calcula
relevância. Output direto consumido pelo Coach Synthesis (Etapa 3b)
como contexto para a recomendação.

Regras de match:
- Underestimation pattern aplica a issue se issue.assignee == pattern.assignee
  AND pattern.label ∈ issue.labels.
- Carryover pattern aplica se pattern.label ∈ issue.labels.

Relevância = pattern.confidence (proxy decente para MVP). Em produção,
incorporaríamos similaridade semântica entre a issue atual e as evidence
issues do pattern.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import IssueRow
from app.services.mining.models import CrossRefHit, Pattern, PatternType

log = get_logger(__name__)


async def detect(
    session: AsyncSession, project_id: int, patterns: list[Pattern]
) -> list[CrossRefHit]:
    if not patterns:
        return []

    open_issues = (
        await session.scalars(
            select(IssueRow)
            .where(IssueRow.project_id == project_id)
            .where(IssueRow.issue_type != "Epic")
            .where(IssueRow.status.in_(["To Do", "In Progress"]))
        )
    ).all()

    hits: list[CrossRefHit] = []

    for issue in open_issues:
        issue_labels = set(issue.labels or [])
        if not issue_labels:
            continue

        for pattern in patterns:
            ev = pattern.evidence
            label = ev.get("label")
            if not label or label not in issue_labels:
                continue

            ptype = (
                pattern.type
                if isinstance(pattern.type, PatternType)
                else PatternType(pattern.type)
            )

            if ptype is PatternType.UNDERESTIMATION:
                if issue.assignee_account_id != ev.get("assignee_account_id"):
                    continue
                rationale = (
                    f"{issue.key} é de {ev.get('assignee_display_name')} "
                    f"em '{label}' — cluster onde a estimativa final foi "
                    f"em média {ev.get('avg_ratio')}× a inicial em "
                    f"{ev.get('n')} entregas anteriores."
                )
            elif ptype is PatternType.CARRYOVER:
                rationale = (
                    f"{issue.key} tem label '{label}' — "
                    f"esse tipo de trabalho carregou em "
                    f"{int(ev.get('carryover_rate', 0) * 100)}% das últimas "
                    f"{ev.get('n_total')} sprints."
                )
            else:
                continue

            hits.append(
                CrossRefHit(
                    issue_key=issue.key,
                    pattern_type=ptype,
                    relevance=pattern.confidence,
                    rationale=rationale,
                    pattern_evidence=ev,
                    pattern_evidence_keys=pattern.evidence_keys,
                )
            )

    log.info("cross_refs_detected", count=len(hits))
    return hits
