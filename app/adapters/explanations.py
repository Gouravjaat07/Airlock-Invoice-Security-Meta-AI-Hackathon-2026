"""Explanation layer: deterministic template explainer (default).

The explainer receives ONLY the policy verdict, rule results, and safe
field summaries -- never raw documents, OCR text, or transcripts. It
explains an existing decision; it cannot change it. A future Spark
planner adapter must respect the same input boundary.
"""

from __future__ import annotations

from typing import Protocol

from app.domain.enums import Verdict
from app.domain.verdicts import RuleResult

ADAPTER_ID = "template-explainer"
ADAPTER_VERSION = "2.0.0"


class Explainer(Protocol):
    adapter_id: str
    adapter_version: str

    def explain(self, verdict: Verdict, rules: list[RuleResult]) -> str:
        ...


class TemplateExplainer:
    adapter_id = ADAPTER_ID
    adapter_version = ADAPTER_VERSION

    def explain(self, verdict: Verdict, rules: list[RuleResult]) -> str:
        passed = [rule.rule_id for rule in rules if rule.passed]
        failed = [(rule.rule_id, rule.reason_code, rule.message)
                  for rule in rules if not rule.passed]
        lines = [f"Verdict: {verdict.value}."]
        if passed:
            lines.append(f"Checks passed: {', '.join(passed)}.")
        for rule_id, reason, message in failed:
            lines.append(f"{rule_id} ({reason}): {message}.")
        if verdict == Verdict.ALLOW_PROPOSAL:
            lines.append("A payment proposal may be created. Owner approval is still required.")
        elif verdict == Verdict.ESCALATE:
            lines.append("This case needs owner review before any proposal can be created.")
        else:
            lines.append("No payment proposal can be created for this case.")
        return " ".join(lines)
