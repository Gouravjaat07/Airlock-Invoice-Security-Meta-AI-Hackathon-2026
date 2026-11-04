"""Domain enumerations: verdicts, states, validation status."""

from __future__ import annotations

from enum import Enum


class Verdict(str, Enum):
    ALLOW_PROPOSAL = "ALLOW_PROPOSAL"
    ESCALATE = "ESCALATE"
    DENY = "DENY"


class CaseState(str, Enum):
    UPLOADED = "UPLOADED"
    READING = "READING"
    CORROBORATING = "CORROBORATING"
    VERDICT = "VERDICT"
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    EXECUTED = "EXECUTED"
    REJECTED = "REJECTED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    ERROR = "ERROR"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class FieldStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    CONFLICT = "CONFLICT"
    UNCONFIRMED = "UNCONFIRMED"
    NOT_PROVIDED = "NOT_PROVIDED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ProposalStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"


class PaymentStatus(str, Enum):
    MOCK_COMPLETED = "MOCK_COMPLETED"
    FAILED = "FAILED"


class ActorType(str, Enum):
    OWNER = "owner"
    SYSTEM = "system"
    ANONYMOUS = "anonymous"
