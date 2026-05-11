"""Orquestrador do Pattern Mining."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.services.mining import carryover, underestimation
from app.services.mining.models import Pattern

log = get_logger(__name__)


class MiningService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def run(self, project_id: int) -> list[Pattern]:
        patterns: list[Pattern] = []
        for name, detector in (
            ("underestimation", underestimation.detect),
            ("carryover", carryover.detect),
        ):
            try:
                found = await detector(self.session, project_id)
            except Exception as e:
                log.exception("mining_detector_failed", detector=name, error=str(e))
                continue
            patterns.extend(found)

        log.info("mining_complete", patterns=len(patterns))
        return patterns
