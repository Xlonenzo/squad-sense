"""Coach Agent — pipeline multi-step "abordagem própria".

Etapas:
1. Hygiene Pass (algorítmico, etapa 3a)
2. Pattern Mining (longitudinal, etapa 3b)
3. Cross-Reference (cruzamento padrão histórico × issue aberta)
4. Trigger building (consolida findings + cross-refs em "unidades de
   recomendação")
5. RAG (puxa texto completo das issues citadas como evidência)
6. Synthesis (LLM gera comment_body por trigger, em paralelo com
   limite de concorrência; system prompt cacheado)
7. Persist (recommendation table com status='proposed')

Não usa LangGraph aqui. Pipeline é linear e curto; um framework
adicionaria peso sem benefício para o escopo. Quando MCP entrar (3c)
e o loop de tools precisar de ramificação dinâmica, aí promovemos.
"""

import asyncio
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.prompts import SYSTEM_PROMPT, render_user_prompt
from app.clients.llm import LLMClient, LLMResponse
from app.core.exceptions import BootstrapError
from app.core.logging import get_logger
from app.db.models import IssueRow, ProjectRow, RecommendationRow
from app.services.cross_reference import detect as cross_reference_detect
from app.services.hygiene.models import Finding, FindingType
from app.services.hygiene.service import HygieneService
from app.services.mining.models import CrossRefHit, Pattern, PatternType
from app.services.mining.service import MiningService

log = get_logger(__name__)

# Limita concorrência de chamadas LLM para não estourar rate limits.
LLM_CONCURRENCY = 5


# ------------------------------------------------------------------ types


_FINDING_TO_REC_TYPE = {
    FindingType.DEDUP_CANDIDATE.value: "dedup",
    FindingType.OBSOLETE.value: "obsolete_review",
    FindingType.DOR_VIOLATION.value: "dor_fix",
    FindingType.EMERGING_EPIC.value: "emerging_epic",
}

_PATTERN_TO_REC_TYPE = {
    PatternType.UNDERESTIMATION.value: "underestimation_warning",
    PatternType.CARRYOVER.value: "carryover_warning",
}


class Trigger(BaseModel):
    """Unidade que vira UMA recomendação. Pode vir de uma finding, de
    cross-refs em uma issue, ou de um pattern standalone."""

    rec_type: str
    severity: str
    confidence: float
    target_keys: list[str]
    evidence: dict[str, Any]
    evidence_issue_keys: list[str] = Field(default_factory=list)


class CoachRunStats(BaseModel):
    project_key: str
    findings_count: int
    patterns_count: int
    cross_refs_count: int
    triggers_count: int
    recommendations_persisted: int
    llm_model: str
    llm_input_tokens_total: int
    llm_cached_input_tokens_total: int
    llm_output_tokens_total: int


# ----------------------------------------------------------------- agent


class CoachAgent:
    def __init__(self, session: AsyncSession, llm: LLMClient):
        self.session = session
        self.llm = llm

    async def run(self, project_key: str) -> CoachRunStats:
        project = (
            await self.session.scalars(
                select(ProjectRow).where(ProjectRow.key == project_key)
            )
        ).first()
        if project is None:
            raise BootstrapError(
                f"projeto {project_key} não encontrado. /ingest/run primeiro."
            )

        # 1+2+3 — análises
        hygiene = await HygieneService(self.session).run(project_key)
        patterns = await MiningService(self.session).run(project.id)
        cross_refs = await cross_reference_detect(self.session, project.id, patterns)

        # 4 — triggers
        triggers = self._build_triggers(hygiene.findings, patterns, cross_refs)

        # 5+6 — RAG enrichment + LLM em paralelo (com cap de concorrência)
        responses = await self._synthesize_all(triggers)

        # 7 — persist
        persisted = await self._persist(project.id, triggers, responses)

        # Telemetria de tokens (útil para observar prompt-cache funcionando)
        in_total = sum(r.input_tokens for r in responses)
        cache_in_total = sum(r.cached_input_tokens for r in responses)
        out_total = sum(r.output_tokens for r in responses)

        log.info(
            "coach_run_complete",
            project_key=project_key,
            findings=len(hygiene.findings),
            patterns=len(patterns),
            cross_refs=len(cross_refs),
            triggers=len(triggers),
            persisted=persisted,
            input_tokens=in_total,
            cached=cache_in_total,
            output_tokens=out_total,
            llm_model=self.llm.model,
        )

        return CoachRunStats(
            project_key=project_key,
            findings_count=len(hygiene.findings),
            patterns_count=len(patterns),
            cross_refs_count=len(cross_refs),
            triggers_count=len(triggers),
            recommendations_persisted=persisted,
            llm_model=self.llm.model,
            llm_input_tokens_total=in_total,
            llm_cached_input_tokens_total=cache_in_total,
            llm_output_tokens_total=out_total,
        )

    # ----------------------------------------------------------- triggers

    def _build_triggers(
        self,
        findings: list[Finding],
        patterns: list[Pattern],
        cross_refs: list[CrossRefHit],
    ) -> list[Trigger]:
        triggers: list[Trigger] = []

        # 1 trigger por hygiene finding
        for f in findings:
            ftype = f.type if isinstance(f.type, str) else f.type.value
            rec_type = _FINDING_TO_REC_TYPE.get(ftype)
            if rec_type is None:
                continue
            severity = f.severity if isinstance(f.severity, str) else f.severity.value
            triggers.append(
                Trigger(
                    rec_type=rec_type,
                    severity=severity,
                    confidence=f.confidence,
                    target_keys=list(f.target_keys),
                    evidence={
                        "finding_type": ftype,
                        "rationale": f.rationale,
                        **f.evidence,
                    },
                    evidence_issue_keys=list(f.target_keys),
                )
            )

        # 1 trigger por (issue × pattern_type) com cross-ref
        # Agrupando por issue_key, pattern_type
        cross_by_issue: dict[tuple[str, str], list[CrossRefHit]] = {}
        for cr in cross_refs:
            ptype = (
                cr.pattern_type
                if isinstance(cr.pattern_type, str)
                else cr.pattern_type.value
            )
            cross_by_issue.setdefault((cr.issue_key, ptype), []).append(cr)

        for (issue_key, ptype), hits in cross_by_issue.items():
            rec_type = _PATTERN_TO_REC_TYPE.get(ptype)
            if rec_type is None:
                continue
            top = max(hits, key=lambda h: h.relevance)
            severity = "high" if top.relevance >= 0.75 else (
                "medium" if top.relevance >= 0.5 else "low"
            )
            evidence_keys = sorted(
                {k for h in hits for k in h.pattern_evidence_keys}
            )
            triggers.append(
                Trigger(
                    rec_type=rec_type,
                    severity=severity,
                    confidence=top.relevance,
                    target_keys=[issue_key],
                    evidence={
                        "pattern_type": ptype,
                        "rationale": top.rationale,
                        "pattern_evidence": top.pattern_evidence,
                        "matched_evidence_keys": evidence_keys,
                    },
                    evidence_issue_keys=evidence_keys,
                )
            )

        # 1 trigger standalone por pattern de alta confiança que não
        # ativou nenhuma cross-ref (ainda assim é informação de saúde)
        cross_pattern_types = {ptype for (_, ptype) in cross_by_issue}
        for p in patterns:
            ptype = p.type if isinstance(p.type, str) else p.type.value
            if ptype in cross_pattern_types:
                continue
            if p.confidence < 0.7:
                continue
            rec_type = _PATTERN_TO_REC_TYPE.get(ptype)
            if rec_type is None:
                continue
            triggers.append(
                Trigger(
                    rec_type=rec_type,
                    severity="medium",
                    confidence=p.confidence,
                    target_keys=[],  # padrão sem alvo específico
                    evidence={
                        "pattern_type": ptype,
                        "rationale": p.rationale,
                        "pattern_evidence": p.evidence,
                        "n_observations": p.n_observations,
                    },
                    evidence_issue_keys=p.evidence_keys,
                )
            )

        return triggers

    # ---------------------------------------------------------------- RAG

    async def _rag_load_evidence_issues(self, keys: list[str]) -> list[dict[str, Any]]:
        """Carrega texto completo das issues citadas como evidência.

        Esse é o RAG: trazer, por similaridade ou por chave, os documentos
        que sustentam a recomendação para o LLM citar literalmente.
        """
        if not keys:
            return []
        rows = (
            await self.session.scalars(
                select(IssueRow).where(IssueRow.key.in_(keys))
            )
        ).all()
        return [
            {
                "key": r.key,
                "summary": r.summary,
                "status": r.status,
                "labels": list(r.labels or []),
                "assignee": r.assignee_display_name,
                "story_points_estimated": r.story_points_estimated,
                "story_points_actual": r.story_points_actual,
            }
            for r in rows
        ]

    # ---------------------------------------------------------- synthesis

    async def _synthesize_all(self, triggers: list[Trigger]) -> list[LLMResponse]:
        sem = asyncio.Semaphore(LLM_CONCURRENCY)

        async def one(t: Trigger) -> LLMResponse:
            async with sem:
                return await self._synthesize_one(t)

        return await asyncio.gather(*[one(t) for t in triggers])

    async def _synthesize_one(self, t: Trigger) -> LLMResponse:
        evidence_issues = await self._rag_load_evidence_issues(
            t.evidence_issue_keys
        )

        finding_dict: dict[str, Any] = {
            "rec_type": t.rec_type,
            "severity": t.severity,
            "confidence": t.confidence,
            "target_keys": t.target_keys,
            "evidence": t.evidence,
            "evidence_issues_full": evidence_issues,
        }

        return await self.llm.complete_json(
            system=SYSTEM_PROMPT,
            user=render_user_prompt(finding_dict),
            max_tokens=600,
        )

    # ------------------------------------------------------------ persist

    async def _persist(
        self,
        project_id: int,
        triggers: list[Trigger],
        responses: list[LLMResponse],
    ) -> int:
        now = datetime.now(timezone.utc)
        count = 0
        for t, r in zip(triggers, responses, strict=True):
            row = RecommendationRow(
                project_id=project_id,
                type=t.rec_type,
                status="proposed",
                severity=t.severity,
                confidence=t.confidence,
                target_keys=t.target_keys,
                summary=r.summary[:500],
                comment_body=r.body,
                evidence=t.evidence,
                evidence_issue_keys=t.evidence_issue_keys,
                model_used=r.model,
                created_at=now,
                updated_at=now,
            )
            self.session.add(row)
            count += 1
        await self.session.flush()
        return count
