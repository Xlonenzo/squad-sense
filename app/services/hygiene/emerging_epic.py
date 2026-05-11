"""Detector de epic emergente.

Sinal: existem N issues no backlog que (a) compartilham um tema
(via labels), (b) não estão sob nenhum epic comum, (c) são semanticamente
próximas. Isso indica que falta um epic explícito — o trabalho está
fragmentado.

Algoritmo:
1. SQL: para cada label, conta issues abertas SEM epic_key. Filtra
   labels com >= MIN_CLUSTER_SIZE candidatos.
2. Para cada label candidato, computa similaridade média par a par via
   pgvector. Se >= MIN_AVG_SIMILARITY, emite finding sugerindo agrupar.

Plant P5 do dataset: 6 issues com label 'notifications', todas TODO,
todas sem epic — devem cair aqui.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.services.hygiene.models import Finding, FindingType, Severity

log = get_logger(__name__)

MIN_CLUSTER_SIZE = 4
MIN_AVG_SIMILARITY = 0.40  # cosine sim


async def detect(session: AsyncSession, project_id: int) -> list[Finding]:
    await session.execute(text("SET LOCAL ivfflat.probes = 100"))

    # Passo 1: clusters candidatos por label
    candidates = (
        await session.execute(
            text(
                """
                SELECT label,
                       array_agg(id ORDER BY id) AS issue_ids,
                       array_agg(key ORDER BY id) AS issue_keys,
                       array_agg(summary ORDER BY id) AS summaries
                FROM (
                  SELECT i.id, i.key, i.summary,
                         jsonb_array_elements_text(i.labels::jsonb) AS label
                  FROM issue i
                  WHERE i.project_id = :project_id
                    AND i.status = 'To Do'
                    AND i.issue_type <> 'Epic'
                    AND i.epic_key IS NULL
                ) expanded
                GROUP BY label
                HAVING COUNT(*) >= :min_size
                """
            ),
            {"project_id": project_id, "min_size": MIN_CLUSTER_SIZE},
        )
    ).all()

    findings: list[Finding] = []
    for label, ids, keys, summaries in candidates:
        # Passo 2: similaridade média par-a-par
        avg_distance = await _avg_pairwise_distance(session, ids)
        if avg_distance is None:
            continue

        avg_sim = 1.0 - avg_distance
        if avg_sim < MIN_AVG_SIMILARITY:
            continue

        findings.append(
            Finding(
                type=FindingType.EMERGING_EPIC,
                severity=_severity(len(ids), avg_sim),
                confidence=round(min(avg_sim + 0.1, 1.0), 3),
                target_keys=list(keys),
                rationale=(
                    f"{len(ids)} issues compartilham o tema '{label}' "
                    f"(similaridade média {avg_sim:.2f}) sem nenhum epic "
                    f"associado. Considere criar um epic 'Sistema de "
                    f"{label.title()}' para dar visibilidade ao escopo."
                ),
                evidence={
                    "label": label,
                    "cluster_size": len(ids),
                    "avg_similarity": round(avg_sim, 4),
                    "suggested_epic_name": f"Sistema de {label.title()}",
                    "summaries": list(summaries),
                },
            )
        )

    log.info("emerging_epic_detected", count=len(findings))
    return findings


async def _avg_pairwise_distance(
    session: AsyncSession, ids: list[int]
) -> float | None:
    if len(ids) < 2:
        return None
    result = await session.execute(
        text(
            """
            SELECT AVG(ea.embedding <=> eb.embedding) AS avg_distance
            FROM issue_embedding ea
            JOIN issue_embedding eb ON ea.issue_id < eb.issue_id
            WHERE ea.issue_id = ANY(:ids)
              AND eb.issue_id = ANY(:ids)
            """
        ),
        {"ids": ids},
    )
    val = result.scalar()
    return float(val) if val is not None else None


def _severity(size: int, avg_sim: float) -> Severity:
    # Cluster maior + mais coeso = mais óbvio.
    if size >= 6 and avg_sim >= 0.5:
        return Severity.HIGH
    if size >= 5 or avg_sim >= 0.5:
        return Severity.MEDIUM
    return Severity.LOW
