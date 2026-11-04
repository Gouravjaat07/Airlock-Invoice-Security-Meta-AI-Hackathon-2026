"""Proposal domain: canonical hash over authorized fields."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.canonical_json import canonical_sha256


def proposal_digest(*, proposal_id: str, case_id: str, vendor_id: str,
                   amount: str, currency: str, due_date: str,
                   invoice_reference: str, verdict_id: str,
                   policy_version: str) -> str:
    """Stable SHA-256 over exactly the owner-authorized values."""
    return canonical_sha256({
        "proposal_id": proposal_id,
        "case_id": case_id,
        "vendor_id": vendor_id,
        "amount": amount,
        "currency": currency,
        "due_date": due_date,
        "invoice_reference": invoice_reference,
        "verdict_id": verdict_id,
        "policy_version": policy_version,
    })


@dataclass
class Proposal:
    proposal_id: str
    case_id: str
    vendor_id: str
    payee_display_name: str
    amount: str  # canonical Decimal string
    currency: str
    due_date: str  # ISO date
    invoice_reference: str
    verdict_id: str
    policy_version: str
    proposal_hash: str
    created_at: str
    expires_at: str
    status: str
