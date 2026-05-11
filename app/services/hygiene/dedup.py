"""Detector de duplicatas semânticas no backlog atual.

Estratégia: pgvector self-join sobre issue_embedding com cosine distance.
Filtros:
- Apenas issues abertas (skip Done) — não interessa dedupar histórico fechado.
- Skip pares que já compartilham epic_key (intencionalmente similares).
- Distância < 0.30 (similaridade > 0.70) — calibrado em smoke da etapa 2.

A severity é função da distância: quanto mais perto, mais alta a confiança
de que é duplicata real.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.services.hygiene.models import Finding, FindingType, Severity

log = get_logger(__name__)

MAX_DISTANCE = 0.30  # similaridade ≥ 0.70


def _severity(distance: float) -> Severity:
    if distance < 0.20:  # sim > 0.80
        return Severity.HIGH
    if distance < 0.25:  # sim > 0.75
        return Severity.MEDIUM
    return Severity.LOW


async def detect(session: AsyncSession, project_id: int) -> list[Finding]:
    # IVFFlat lists=100 sobredimensionado para o tamanho do demo: aumenta
    # probes para varrer todas as células. Em produção (>1k issues) o
    # default funciona, mas mantemos explícito para reprodutibilidade.
    await session.execute(text("SET LOCAL ivfflat.probes = 100"))

    sql = text(
        """
        SELECT a.key AS key_a,
               b.key AS key_b,
               a.summary AS summary_a,
               b.summary AS summary_b,
               a.status  AS status_a,
               b.status  AS status_b,
               a.labels  AS labels_a,
               b.labels  AS labels_b,
               (ea.embedding <=> eb.embedding) AS distance
        FROM issue a
        JOIN issue_embedding ea ON ea.issue_id = a.id
        JOIN issue_embedding eb ON ea.id <> eb.id
        JOIN issue b ON b.id = eb.issue_id
        WHERE a.id < b.id
          AND a.project_id = :project_id
          AND b.project_id = :project_id
          AND a.status <> 'Done'
          AND b.status <> 'Done'
          AND a.issue_type <> 'Epic'
          AND b.issue_type <> 'Epic'
          AND (
              a.epic_key IS NULL OR b.epic_key IS NULL OR a.epic_key <> b.epic_key
          )
          AND (ea.embedding <=> eb.embedding) < :max_distance
        ORDER BY distance ASC
        LIMIT 50
        """
    )
    rows = (
        await session.execute(
            sql, {"project_id": project_id, "max_distance": MAX_DISTANCE}
        )
    ).all()

    findings: list[Finding] = []
    for r in rows:
        distance = float(r.distance)
        similarity = 1.0 - distance
        findings.append(
            Finding(
                type=FindingType.DEDUP_CANDIDATE,
                severity=_severity(distance),
                confidence=round(similarity, 3),
                target_keys=[r.key_a, r.key_b],
                rationale=(
                    f"{r.key_a} e {r.key_b} têm similaridade semântica de "
                    f"{similarity:.2f} — provável duplicata. "
                    f"'{_truncate(r.summary_a)}' vs '{_truncate(r.summary_b)}'."
                ),
                evidence={
                    "similarity": round(similarity, 4),
                    "distance": round(distance, 4),
                    "labels_a": list(r.labels_a or []),
                    "labels_b": list(r.labels_b or []),
                    "status_a": r.status_a,
                    "status_b": r.status_b,
                    "summary_a": r.summary_a,
                    "summary_b": r.summary_b,
                },
            )
        )

    log.info("dedup_detected", count=len(findings))
    return findings


def _truncate(s: str, n: int = 60) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"
