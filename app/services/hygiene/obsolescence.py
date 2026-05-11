"""Detector de issues obsoletas — abertas há muito tempo sem atividade.

Sinal: 'esse trabalho ainda faz sentido?' Se ninguém tocou em 6+ meses,
ou o problema sumiu ou foi resolvido por outro caminho. Em qualquer
hipótese, mantê-lo no backlog enviesa priorização.

Severity por idade: 1y+ → HIGH, 6-12m → MEDIUM, <6m mas >180d → LOW.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import IssueRow
from app.services.hygiene.models import Finding, FindingType, Severity

log = get_logger(__name__)

OBSOLETE_DAYS = 180


def _severity(days: int) -> Severity:
    if days >= 365:
        return Severity.HIGH
    if days >= 270:
        return Severity.MEDIUM
    return Severity.LOW


def _confidence(days: int) -> float:
    # Sigmoide leve centrada em 365: vira 0.5 com 1 ano, →1 com 2 anos.
    score = (days - 180) / 365
    return max(0.0, min(1.0, 0.5 + 0.5 * score))


async def detect(session: AsyncSession, project_id: int) -> list[Finding]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=OBSOLETE_DAYS)
    stmt = (
        select(IssueRow)
        .where(IssueRow.project_id == project_id)
        .where(IssueRow.status != "Done")
        .where(IssueRow.issue_type != "Epic")
        .where(IssueRow.last_activity_at < cutoff)
        .order_by(IssueRow.last_activity_at)
    )
    rows = (await session.scalars(stmt)).all()

    now = datetime.now(timezone.utc)
    findings: list[Finding] = []
    for issue in rows:
        last = issue.last_activity_at or issue.created_at
        # Se vier sem tz (caso bizarro), assume UTC para não explodir
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        days = (now - last).days

        findings.append(
            Finding(
                type=FindingType.OBSOLETE,
                severity=_severity(days),
                confidence=round(_confidence(days), 3),
                target_keys=[issue.key],
                rationale=(
                    f"{issue.key} está aberta há {days} dias sem atividade. "
                    f"Considere arquivar ou justificar manutenção no backlog."
                ),
                evidence={
                    "days_inactive": days,
                    "last_activity_at": last.isoformat(),
                    "summary": issue.summary,
                    "status": issue.status,
                    "labels": list(issue.labels or []),
                },
            )
        )

    log.info("obsolete_detected", count=len(findings))
    return findings
