"""Schemas dos padrões longitudinais e dos cross-refs.

Distinção importante:
- Finding (hygiene): algo errado com o presente (duplicata, obsoleta...)
- Pattern (mining): regularidade ao longo do tempo (joão estoura prazo
  em integrações; tech-debt carrega 70%...)
- CrossRefHit: ponte entre uma issue aberta hoje e um Pattern histórico —
  é o que o Coach Synthesis usa para narrar a recomendação.
"""

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PatternType(str, Enum):
    UNDERESTIMATION = "underestimation"
    CARRYOVER = "carryover"


class Pattern(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    type: PatternType
    confidence: float = Field(ge=0.0, le=1.0)
    n_observations: int = Field(ge=1)
    rationale: str
    evidence: dict[str, Any]
    evidence_keys: list[str] = Field(
        default_factory=list,
        description="Issue keys históricas que sustentam esse padrão. "
        "Usadas como evidência citável pelo Coach Synthesis (RAG).",
    )


class CrossRefHit(BaseModel):
    """Aplicação de um Pattern a uma issue aberta no presente."""

    model_config = ConfigDict(use_enum_values=True)

    issue_key: str
    pattern_type: PatternType
    relevance: float = Field(ge=0.0, le=1.0)
    rationale: str
    pattern_evidence: dict[str, Any]
    pattern_evidence_keys: list[str]


class MiningReport(BaseModel):
    project_key: str
    patterns_count: int
    patterns: list[Pattern]
    cross_refs_count: int
    cross_refs: list[CrossRefHit]
