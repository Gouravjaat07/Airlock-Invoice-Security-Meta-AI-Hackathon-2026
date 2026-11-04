"""Deterministic proposal builder (application code, never model text).

Proposals are created only from ALLOW verdicts. The canonical hash covers
exactly the owner-authorized values; display text cannot affect it.
"""

from __future__ import annotations

import sqlite3
from datetime import timedelta

from app.config import Settings
from app.core.clock import SYSTEM_CLOCK
from app.core.errors import AppError, ErrorCode
from app.core.ids import new_id
from app.core.security import constant_time_equal
from app.domain.proposals import proposal_digest
from app.domain.verdicts import RuleResult
from app.pipeline.corroborate import quantize_money
from app.schemas.invoice import InvoiceExtraction
from app.storage.repositories import InvoiceIndexRepository, ProposalRepository

_proposals = ProposalRepository()
_index = InvoiceIndexRepository()


def build_proposal(conn: sqlite3.Connection, settings: Settings, *,
                   case_id: str, extraction: InvoiceExtraction, vendor: dict,
                   verdict_id: str, rules: list[RuleResult]) -> dict:
    """Insert proposal + reserve duplicate key. Call inside a transaction."""
    for rule in rules:
        if not rule.passed:  # defense in depth: only ALLOW input accepted
            raise AppError(ErrorCode.POLICY_DENY,
                           "Refusing to build a proposal from a failed verdict")
    amount = str(quantize_money(extraction.total, settings.currency_precision))
    now = SYSTEM_CLOCK.now()
    expires = now + timedelta(minutes=settings.proposal_ttl_minutes)
    proposal_id = new_id("prop")
    digest = proposal_digest(
        proposal_id=proposal_id, case_id=case_id,
        vendor_id=str(vendor["vendor_id"]), amount=amount,
        currency=extraction.currency, due_date=extraction.due_date.isoformat(),
        invoice_reference=extraction.invoice_number, verdict_id=verdict_id,
        policy_version=settings.policy_version)
    _proposals.create(
        conn, proposal_id=proposal_id, case_id=case_id,
        vendor_id=str(vendor["vendor_id"]),
        payee=str(vendor["name"]), amount=amount,
        currency=extraction.currency,
        due_date=extraction.due_date.isoformat(),
        invoice_ref=extraction.invoice_number, verdict_id=verdict_id,
        proposal_hash=digest, policy_version=settings.policy_version,
        expires_at=expires.isoformat(), now=now.isoformat())
    dup_key = _dup_key(settings, vendor_id=str(vendor["vendor_id"]),
                       extraction=extraction)
    _index.insert(conn, dup_key=dup_key, vendor_id=str(vendor["vendor_id"]),
                  case_id=case_id,
                  number_norm=extraction.invoice_number.strip().upper(),
                  total=amount, issue_date=extraction.issue_date.isoformat(),
                  status="proposed", now=now.isoformat())
    row = _proposals.get(conn, proposal_id)
    assert row is not None
    return row


def _dup_key(settings: Settings, *, vendor_id: str,
             extraction: InvoiceExtraction) -> str:
    from app.pipeline.corroborate import duplicate_key
    return duplicate_key(vendor_id=vendor_id,
                         invoice_number=extraction.invoice_number,
                         total=extraction.total,
                         issue_date=extraction.issue_date,
                         precision=settings.currency_precision)


def verify_proposal_hash(proposal: dict) -> bool:
    """Recompute the canonical hash; False on any payment-data tampering."""
    expected = proposal_digest(
        proposal_id=str(proposal["proposal_id"]), case_id=str(proposal["case_id"]),
        vendor_id=str(proposal["vendor_id"]), amount=str(proposal["amount"]),
        currency=str(proposal["currency"]), due_date=str(proposal["due_date"]),
        invoice_reference=str(proposal["invoice_reference"]),
        verdict_id=str(proposal["verdict_id"]),
        policy_version=str(proposal["policy_version"]))
    return constant_time_equal(expected, str(proposal["proposal_hash"]))
