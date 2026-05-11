from datetime import datetime
from typing import Any

from pydantic import BaseModel


class RecommendationOut(BaseModel):
    id: int
    type: str
    status: str
    severity: str
    confidence: float
    target_keys: list[str]
    summary: str
    comment_body: str
    evidence: dict[str, Any]
    evidence_issue_keys: list[str]
    model_used: str
    human_feedback: str | None
    jira_comment_id: str | None
    created_at: datetime
    updated_at: datetime


class RecommendationFeedbackIn(BaseModel):
    status: str  # "accepted" | "rejected"
    human_feedback: str | None = None
