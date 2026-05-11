"""Detector de violação de Definition of Ready (DoR).

Heurísticas determinísticas. Não tentamos avaliar 'qualidade' do
description com LLM aqui — isso fica para 3b. Aqui só checamos se as
peças mínimas existem:

- Description com conteúdo (>50 chars)
- Marcador de critérios de aceitação (AC:, Given/When/Then, "deve"...)
- Story points estimado
- Assignee, se a issue está em sprint ativa

Em produção um DoR é negociado por squad; este é um starter pack que
o time customiza. O agente vai usar isso como sinal, não como verdade.
"""

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.logging import get_logger
from app.db.models import IssueRow, SprintRow
from app.services.hygiene.models import Finding, FindingType, Severity

log = get_logger(__name__)

MIN_DESCRIPTION_LEN = 50

AC_PATTERNS = [
    r"\bAC[:\s]",
    r"crit[ée]rios?\s+de\s+aceita[çc][ãa]o",
    r"\bgiven\b.+\bwhen\b.+\bthen\b",
    r"\bquando\b.+\bent[ãa]o\b",
    r"\bdado\b.+\bquando\b.+\bent[ãa]o\b",
]
_AC_RE = re.compile("|".join(AC_PATTERNS), re.IGNORECASE | re.DOTALL)


def _has_acceptance_criteria(description: str | None) -> bool:
    if not description:
        return False
    return bool(_AC_RE.search(description))


def _confidence_for_count(missing_count: int) -> float:
    if missing_count >= 3:
        return 0.95
    if missing_count == 2:
        return 0.85
    return 0.6  # 1 missing — pode ser intencional / em comment


def _severity_for_count(missing_count: int) -> Severity:
    if missing_count >= 3:
        return Severity.HIGH
    if missing_count == 2:
        return Severity.MEDIUM
    return Severity.LOW


async def detect(session: AsyncSession, project_id: int) -> list[Finding]:
    stmt = (
        select(IssueRow)
        .where(IssueRow.project_id == project_id)
        .where(IssueRow.issue_type != "Epic")
        .where(IssueRow.status.in_(["To Do", "In Progress"]))
        .options(selectinload(IssueRow.sprint))
    )
    rows = (await session.scalars(stmt)).all()

    findings: list[Finding] = []
    for issue in rows:
        missing: list[str] = []

        desc = (issue.description or "").strip()
        if len(desc) < MIN_DESCRIPTION_LEN:
            missing.append("description_short_or_missing")

        if not _has_acceptance_criteria(desc):
            missing.append("no_acceptance_criteria")

        if issue.story_points_estimated is None or issue.story_points_estimated <= 0:
            missing.append("no_story_points")

        in_active_sprint = (
            issue.sprint is not None and issue.sprint.state == "active"
        )
        if in_active_sprint and not issue.assignee_account_id:
            missing.append("active_sprint_without_assignee")

        if not missing:
            continue

        findings.append(
            Finding(
                type=FindingType.DOR_VIOLATION,
                severity=_severity_for_count(len(missing)),
                confidence=_confidence_for_count(len(missing)),
                target_keys=[issue.key],
                rationale=_rationale(issue.key, missing),
                evidence={
                    "missing": missing,
                    "summary": issue.summary,
                    "status": issue.status,
                    "in_active_sprint": in_active_sprint,
                    "description_length": len(desc),
                },
            )
        )

    log.info("dor_violations_detected", count=len(findings))
    return findings


_HUMAN = {
    "description_short_or_missing": "description ausente/curta",
    "no_acceptance_criteria": "sem critérios de aceitação",
    "no_story_points": "sem story points estimado",
    "active_sprint_without_assignee": "em sprint ativa sem assignee",
}


def _rationale(key: str, missing: list[str]) -> str:
    parts = ", ".join(_HUMAN.get(m, m) for m in missing)
    return f"{key} viola DoR: {parts}."
