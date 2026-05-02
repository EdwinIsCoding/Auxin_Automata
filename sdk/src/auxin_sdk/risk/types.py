"""Risk scoring Pydantic models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class RiskBreakdown(BaseModel):
    """Score contribution from a single risk dimension."""

    category: str
    score: float = Field(ge=0.0, le=100.0)
    weight: float = Field(ge=0.0, le=1.0)
    factors: list[str]


class RiskReport(BaseModel):
    """Complete risk assessment snapshot for a hardware wallet."""

    overall_score: float = Field(ge=0.0, le=100.0)
    grade: str  # A / B / C / D / F
    breakdown: list[RiskBreakdown]
    trend: str  # improving / stable / declining
    trend_data: list[dict[str, Any]]  # [{date: str, score: float}, ...]
    computed_at: datetime
