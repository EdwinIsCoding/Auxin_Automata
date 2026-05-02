"""Treasury agent Pydantic models."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class BudgetAllocation(BaseModel):
    """How the wallet budget is split across categories (percentages, sum = 100)."""

    inference: float = Field(ge=0.0, le=100.0)
    reserve: float = Field(ge=0.0, le=100.0)
    buffer: float = Field(ge=0.0, le=100.0)


class RecommendedAction(BaseModel):
    """A single actionable recommendation from the treasury agent."""

    action: str
    priority: str  # low / medium / high / critical
    reasoning: str
    auto_executable: bool


class TreasuryAnalysis(BaseModel):
    """Complete treasury analysis snapshot from the AI agent."""

    burn_rate_lamports_per_hour: int
    runway_hours: float
    runway_status: str  # healthy / warning / critical
    budget_allocation: BudgetAllocation
    recommended_actions: list[RecommendedAction]
    anomaly_flags: list[str]
    summary: str
    risk_score_context: float | None = None
    analyzed_at: datetime
    used_fallback: bool = False
