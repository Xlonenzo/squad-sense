"""Orquestrador do Hygiene Pass.

Executa os 4 detectores sequencialmente sobre a mesma sessão. Sequencial
porque pgvector queries são micros e SQLAlchemy não tolera sessions
compartilhadas em coroutines paralelas. Quando o volume crescer, cada
detector ganha sua própria session.
"""

from collections import Counter

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BootstrapError
from app.core.logging import get_logger
from app.db.models import ProjectRow
from app.services.hygiene import dedup, dor, emerging_epic, obsolescence
from app.services.hygiene.models import Finding, HygieneReport, Severity

log = get_logger(__name__)

_SEVERITY_ORDER = {Severity.HIGH.value: 0, Severity.MEDIUM.value: 1, Severity.LOW.value: 2}


class HygieneService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def run(self, project_key: str) -> HygieneReport:
        project = (
            await self.session.scalars(
                select(ProjectRow).where(ProjectRow.key == project_key)
            )
        ).first()
        if project is None:
            raise BootstrapError(
                f"projeto {project_key} não encontrado no DB. Rode /ingest/run antes."
            )

        all_findings: list[Finding] = []
        for name, detector in (
            ("dedup", dedup.detect),
            ("obsolescence", obsolescence.detect),
            ("dor", dor.detect),
            ("emerging_epic", emerging_epic.detect),
        ):
            try:
                findings = await detector(self.session, project.id)
            except Exception as e:
                log.exception("detector_failed", detector=name, error=str(e))
                continue
            all_findings.extend(findings)

        all_findings.sort(
            key=lambda f: (_SEVERITY_ORDER.get(f.severity, 99), -f.confidence)
        )

        by_type: Counter[str] = Counter(f.type for f in all_findings)

        log.info(
            "hygiene_run_complete",
            project_key=project_key,
            total=len(all_findings),
            by_type=dict(by_type),
        )

        return HygieneReport(
            project_key=project_key,
            findings_count=len(all_findings),
            findings_by_type=dict(by_type),
            findings=all_findings,
        )
