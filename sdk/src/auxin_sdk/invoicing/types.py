"""Invoice Pydantic models."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

LAMPORTS_PER_SOL = 1_000_000_000


class LineItem(BaseModel):
    """A single payment line item on the invoice."""

    timestamp: datetime
    description: str
    provider_pubkey: str
    lamports: int
    sol_amount: float
    tx_signature: str
    category: str = "inference"


class ComplianceSummaryItem(BaseModel):
    """A compliance event referenced in the invoice."""

    timestamp: datetime
    severity: int
    reason_code: int
    hash: str
    tx_signature: str


class Invoice(BaseModel):
    """Complete compute invoice for a billing period."""

    invoice_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    generated_at: datetime
    period_start: datetime
    period_end: datetime
    hardware_agent_pubkey: str
    line_items: list[LineItem]
    compliance_summary: list[ComplianceSummaryItem]
    total_lamports: int
    total_sol: float
    total_transactions: int
    total_compliance_events: int
    risk_score_at_generation: float | None = None
    treasury_summary: str | None = None
