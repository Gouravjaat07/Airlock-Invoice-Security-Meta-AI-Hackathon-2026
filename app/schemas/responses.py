"""Response models (safe projections only; never secrets)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    version: str
    database: str
    schema_version: int
    policy_version: str


class SessionInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    authenticated: bool
    session_id: str | None = None
    expires_at: str | None = None


class ProposalView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal_id: str
    case_id: str
    vendor_id: str
    payee_display_name: str
    amount: str
    currency: str
    due_date: str
    invoice_reference: str
    verdict_id: str
    policy_version: str
    proposal_hash: str
    created_at: str
    expires_at: str
    status: str
