"""Detector de padrão de subestimação (P1).

Sinal: certas combinações (assignee × label) consistentemente entregam
em N× a estimativa. No nosso dataset: joão.dev em label 'integration'
fechou 4 issues com média 2.1× a estimativa.

Algoritmo:
1. Carregar issues Done com story_points_estimated E story_points_actual
   conhecidos.
2. Expandir uma linha por (issue, label) — issue pode ter múltiplas
   labels relevantes.
3. Agrupar por (assignee, label). Para grupos com N >= 3, calcular
   ratio médio (actual / estimated).
4. Se ratio >= 1.5×, emitir Pattern.

Severity (encoded em confidence): cresce com N e com afastamento de 1.0.
"""

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import IssueRow
from app.services.mining.models import Pattern, PatternType

log = get_logger(__name__)

MIN_OBSERVATIONS = 3
MIN_RATIO = 1.5


async def detect(session: AsyncSession, project_id: int) -> list[Pattern]:
    rows = (
        await session.scalars(
            select(IssueRow)
            .where(IssueRow.project_id == project_id)
            .where(IssueRow.status == "Done")
            .where(IssueRow.story_points_estimated.is_not(None))
            .where(IssueRow.story_points_actual.is_not(None))
            .where(IssueRow.assignee_account_id.is_not(None))
        )
    ).all()

    # (assignee, label) -> [(issue_key, ratio)]
    groups: dict[tuple[str, str], list[tuple[str, float, str]]] = defaultdict(list)
    for issue in rows:
        if not issue.story_points_estimated or issue.story_points_estimated <= 0:
            continue
        ratio = float(issue.story_points_actual) / float(issue.story_points_estimated)
        for label in (issue.labels or []):
            groups[(issue.assignee_account_id, label)].append(
                (issue.key, ratio, issue.assignee_display_name or issue.assignee_account_id)
            )

    patterns: list[Pattern] = []
    for (assignee, label), items in groups.items():
        if len(items) < MIN_OBSERVATIONS:
            continue
        avg_ratio = sum(r for _, r, _ in items) / len(items)
        if avg_ratio < MIN_RATIO:
            continue

        evidence_keys = [k for k, _, _ in items]
        ratios = [round(r, 2) for _, r, _ in items]
        display_name = items[0][2]

        confidence = min(1.0, 0.5 + 0.1 * (len(items) - 3) + 0.2 * (avg_ratio - 1.5))

        patterns.append(
            Pattern(
                type=PatternType.UNDERESTIMATION,
                confidence=round(confidence, 3),
                n_observations=len(items),
                rationale=(
                    f"{display_name} entregou {len(items)} issues com label "
                    f"'{label}' em média {avg_ratio:.2f}× a estimativa. "
                    f"Sinal forte de subestimação sistemática nessa combinação."
                ),
                evidence={
                    "assignee_account_id": assignee,
                    "assignee_display_name": display_name,
                    "label": label,
                    "avg_ratio": round(avg_ratio, 3),
                    "ratios": ratios,
                    "n": len(items),
                },
                evidence_keys=evidence_keys,
            )
        )

    log.info("underestimation_patterns_detected", count=len(patterns))
    return patterns
