"""Detector de padrão de carryover (P2).

Sinal: certas labels têm taxa alta de issues que carregam de uma sprint
para a seguinte. No nosso dataset: tech-debt teve 5/5 issues carregadas
nas últimas 5 sprints.

Heurística operacional para 'carregou':
    issue.created_at < issue.sprint.start_date - 2 dias

Ou seja: a issue foi criada antes da sprint em que terminou — ou ela
foi reatribuída de uma sprint anterior. Em produção real, dá pra
refinar com Jira changelog (sprint_history); no dataset sintético
isso é exato porque controlei os timestamps.

Algoritmo:
1. Carregar issues Done que tenham sprint_id e created_at + sprint dates.
2. Marcar carregadas vs entregues-no-mesmo-sprint.
3. Para cada label, calcular taxa de carryover. Threshold: rate >= 0.5
   AND total >= 3.
"""

from collections import defaultdict
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.logging import get_logger
from app.db.models import IssueRow
from app.services.mining.models import Pattern, PatternType

log = get_logger(__name__)

MIN_OBSERVATIONS = 3
MIN_CARRYOVER_RATE = 0.5
TOLERANCE = timedelta(days=2)


async def detect(session: AsyncSession, project_id: int) -> list[Pattern]:
    rows = (
        await session.scalars(
            select(IssueRow)
            .where(IssueRow.project_id == project_id)
            .where(IssueRow.status == "Done")
            .where(IssueRow.sprint_id.is_not(None))
            .options(selectinload(IssueRow.sprint))
        )
    ).all()

    # label -> {total, carried_over, evidence_keys}
    by_label: dict[str, dict] = defaultdict(
        lambda: {"total": 0, "carried_over": 0, "evidence_keys": []}
    )

    for issue in rows:
        sprint = issue.sprint
        if sprint is None or sprint.start_date is None:
            continue
        carried = issue.created_at + TOLERANCE < sprint.start_date

        for label in (issue.labels or []):
            data = by_label[label]
            data["total"] += 1
            if carried:
                data["carried_over"] += 1
                data["evidence_keys"].append(issue.key)

    patterns: list[Pattern] = []
    for label, data in by_label.items():
        if data["total"] < MIN_OBSERVATIONS:
            continue
        rate = data["carried_over"] / data["total"]
        if rate < MIN_CARRYOVER_RATE:
            continue

        n = data["total"]
        carried = data["carried_over"]

        # Confidence: cresce com a taxa e com N.
        confidence = min(1.0, 0.4 + 0.6 * rate + 0.05 * (n - 3))

        patterns.append(
            Pattern(
                type=PatternType.CARRYOVER,
                confidence=round(confidence, 3),
                n_observations=n,
                rationale=(
                    f"Issues com label '{label}' carregaram em "
                    f"{carried}/{n} ({int(rate * 100)}%) sprints recentes. "
                    f"Indica que o tipo de trabalho está sendo subestimado "
                    f"ou despriorizado consistentemente."
                ),
                evidence={
                    "label": label,
                    "carryover_rate": round(rate, 3),
                    "n_total": n,
                    "n_carried_over": carried,
                },
                evidence_keys=data["evidence_keys"],
            )
        )

    log.info("carryover_patterns_detected", count=len(patterns))
    return patterns
