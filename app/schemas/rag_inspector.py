"""Schema do RAG Inspector — exposto p/ o frontend tornar o RAG visível.

Esse endpoint é deliberadamente didático: serve como prova viva de que
a recomendação foi construída com retrieval (não invenção do LLM).
"""

from pydantic import BaseModel


class VectorNeighbor(BaseModel):
    key: str
    summary: str
    labels: list[str]
    assignee: str | None
    status: str
    distance: float  # cosine distance
    similarity: float  # 1 - distance


class TargetVectorRetrieval(BaseModel):
    target_key: str
    neighbors: list[VectorNeighbor]


class EvidenceIssue(BaseModel):
    key: str
    summary: str
    status: str
    labels: list[str]
    assignee: str | None
    story_points_estimated: float | None
    story_points_actual: float | None
    ratio: float | None  # actual / estimated, se ambos existirem


class RagInspectorOut(BaseModel):
    recommendation_id: int
    target_keys: list[str]
    evidence_issue_keys: list[str]
    model_used: str

    vector_retrieval: list[TargetVectorRetrieval]
    evidence_issues_loaded: list[EvidenceIssue]

    notes: list[str] = []  # observações curtas exibidas no painel
