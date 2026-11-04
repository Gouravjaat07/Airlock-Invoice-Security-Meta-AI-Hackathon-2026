"""Verdict and rule-result domain shapes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.domain.enums import Verdict


@dataclass(frozen=True)
class RuleResult:
    rule_id: str
    rule_version: str
    passed: bool
    outcome: Verdict | None  # failure outcome when not passed, else None
    reason_code: str
    message: str
    evidence: dict[str, Any] = field(default_factory=dict)
    evaluated_at: str | None = None


@dataclass(frozen=True)
class PolicyVerdict:
    verdict_id: str
    case_id: str
    verdict: Verdict
    reasons: list[str]
    rule_ids: list[str]
    policy_version: str
    created_at: str
