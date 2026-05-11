"""Schema das findings emitidas pelos detectores.

Forma comum acordada para todos os 4 detectores. Mantida explícita
porque a Etapa 3b (Coach Synthesis com Claude) vai consumir isso como
contrato — não como duck typing.
"""

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class FindingType(str, Enum):
    DEDUP_CANDIDATE = "dedup_candidate"
    OBSOLETE = "obsolete"
    DOR_VIOLATION = "dor_violation"
    EMERGING_EPIC = "emerging_epic"


class Severity(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Finding(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    type: FindingType
    severity: Severity
    confidence: float = Field(ge=0.0, le=1.0)

    target_keys: list[str] = Field(
        description="Issue keys que esta finding cobre. >1 quando a finding "
        "é sobre um par/grupo (ex.: dedup, emerging_epic).",
        min_length=1,
    )

    rationale: str = Field(
        description="Explicação curta — por que isso foi flagado. Já "
        "legível em linguagem natural; o Coach (3b) refina, não inventa."
    )

    evidence: dict[str, Any] = Field(
        default_factory=dict,
        description="Dados estruturados que sustentam a finding "
        "(similarity, days_inactive, missing_fields, ...). É a base do RAG "
        "que o LLM da etapa 3b vai citar literalmente.",
    )


class HygieneReport(BaseModel):
    project_key: str
    findings_count: int
    findings_by_type: dict[str, int]
    findings: list[Finding]
