"""Deterministic policy engine R1-R10 (authoritative, no model calls).

Rule meanings are fixed; `policy/rules.toml` supplies thresholds only.
Every rule returns a structured result; aggregation applies explicit
precedence: required-verifier errors -> DENY, R1/R2/R3/R4/R8 -> DENY,
R5/R6/R7/R10 -> ESCALATE, else ALLOW_PROPOSAL.

Interpretations (recorded in docs/phase2/POLICY.md):
- R2 requires a bank reference: missing reference fails R8 instead.
- R5 covers PO problems (unknown/closed/currency/exceeded) as ESCALATE.
- R7 covers optional-evidence conflicts: SAM count mismatch and voice
  conflicts both escalate (SAM is the primary check per the rule table).
"""

from __future__ import annotations

from decimal import Decimal

from app.config import Settings
from app.core.clock import SYSTEM_CLOCK
from app.domain.enums import Verdict
from app.domain.verdicts import RuleResult
from app.pipeline.corroborate import Corroboration
from app.pipeline.evidence import LaneOutcome, LaneStatus
from app.schemas.invoice import InvoiceExtraction

RULE_IDS = ("R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9", "R10")


def _result(rule_id: str, policy_version: str, passed: bool,
            outcome: Verdict | None, reason_code: str, message: str,
            evidence: dict | None = None) -> RuleResult:
    return RuleResult(
        rule_id=rule_id, rule_version=policy_version, passed=passed,
        outcome=outcome if not passed else None, reason_code=reason_code,
        message=message, evidence=evidence or {},
        evaluated_at=SYSTEM_CLOCK.now().isoformat())


def _unevaluated_lanes(sam, voice) -> list[str]:
    """Lanes with uploaded evidence whose comparison never ran.

    Read from corroboration validators (the lane detail strings are
    already bounded there). A verifier error also counts: the
    comparison did not run, so R7 must not claim consistency.
    """
    lanes: list[str] = []
    validators = set(getattr(sam, "validators", []) or [])
    if "sam-not-evaluated" in validators or "sam-required-error" in validators:
        lanes.append("delivery")
    if voice is not None and "voice-not-evaluated" in set(
            getattr(voice, "validators", []) or []):
        lanes.append("voice")
    return lanes


_UNEVALUATED_LANE_STATUSES = frozenset({
    LaneStatus.NOT_EVALUATED, LaneStatus.FAILED, LaneStatus.EMPTY,
})


def _unevaluated_lane_names(*, voice_lane: LaneOutcome | None,
                            sam_lane: LaneOutcome | None) -> list[str]:
    """Lane display names for uploaded-but-unevaluated evidence.

    Used when corroboration is unavailable (extraction failed): the lane
    outcomes still record whether uploaded bytes were compared. MISSING
    means nothing was uploaded (no claim either way); EVALUATED means
    the comparison ran.
    """
    lanes: list[str] = []
    if sam_lane is not None and sam_lane.status in _UNEVALUATED_LANE_STATUSES:
        lanes.append("delivery")
    if voice_lane is not None and voice_lane.status in _UNEVALUATED_LANE_STATUSES:
        lanes.append("voice")
    return lanes


def evaluate_policy(settings: Settings, extraction: InvoiceExtraction | None,
                    corroboration: Corroboration | None, *,
                    schema_ok: bool, schema_errors: list[str] | None = None,
                    required_verifier_errors: list[str] | None = None,
                    voice_lane: LaneOutcome | None = None,
                    sam_lane: LaneOutcome | None = None,
                    ) -> tuple[Verdict, list[RuleResult]]:
    """Evaluate all rules; return (verdict, rule results in R1-R10 order)."""
    version = settings.policy_version
    schema_errors = schema_errors or []
    required_verifier_errors = required_verifier_errors or []
    results: list[RuleResult] = []

    vendor = corroboration.vendor_match.vendor if corroboration else None

    # R1: vendor resolves in the trusted registry.
    if vendor is not None:
        results.append(_result("R1", version, True, None, "vendor-resolved",
                               f"Vendor resolves to {vendor['vendor_id']}",
                               {"vendor_id": vendor["vendor_id"]}))
    else:
        results.append(_result("R1", version, False, Verdict.DENY, "vendor-unresolved",
                               "Vendor does not resolve in the trusted registry"))

    # R2: bank fingerprint matches the active vendor fingerprint.
    if corroboration is None or extraction is None:
        results.append(_result("R2", version, False, Verdict.DENY, "bank-unverifiable",
                               "No corroboration available for bank comparison"))
    elif corroboration.bank_match is True:
        results.append(_result("R2", version, True, None, "bank-match",
                               "Bank fingerprint matches active registry record"))
    elif corroboration.bank_match is False:
        results.append(_result("R2", version, False, Verdict.DENY, "bank-mismatch",
                               "Bank fingerprint does not match the active record"))
    elif not extraction.bank_reference:
        results.append(_result("R2", version, True, None, "bank-not-provided",
                               "No bank reference extracted; R8 decides"))
    else:
        results.append(_result("R2", version, False, Verdict.DENY, "bank-unverifiable",
                               "Bank comparison could not be performed"))

    # R3: exact Decimal arithmetic.
    if corroboration is not None and corroboration.arithmetic_ok:
        results.append(_result("R3", version, True, None, "arithmetic-exact",
                               "Line totals and tax reconcile exactly"))
    else:
        detail = ""
        if corroboration is not None:
            outcome = corroboration.outcomes.get("total")
            detail = f": {outcome.detail}" if outcome else ""
        results.append(_result("R3", version, False, Verdict.DENY, "arithmetic-mismatch",
                               f"Invoice arithmetic does not reconcile{detail}"))

    # R4: duplicate composite key unseen.
    if corroboration is not None and corroboration.duplicate_hit is None \
            and vendor is not None:
        results.append(_result("R4", version, True, None, "not-duplicate",
                               "Invoice identity not previously proposed or paid"))
    elif vendor is None:
        results.append(_result("R4", version, False, Verdict.DENY, "duplicate-unverifiable",
                               "Cannot key duplicate check without a resolved vendor"))
    else:
        results.append(_result("R4", version, False, Verdict.DENY, "duplicate",
                               "Invoice was already proposed or paid"))

    # R5: within cap and PO authorization.
    if extraction is None or corroboration is None:
        results.append(_result("R5", version, False, Verdict.ESCALATE, "cap-unverifiable",
                               "Cannot evaluate cap without extraction"))
    else:
        cap_raw = (vendor.get("per_invoice_cap") if vendor else None) \
            or settings.per_invoice_cap_default
        cap = Decimal(str(cap_raw))
        if extraction.total > cap:
            results.append(_result(
                "R5", version, False, Verdict.ESCALATE, "over-cap",
                f"Total {extraction.total} exceeds cap {cap}",
                {"cap": str(cap), "total": str(extraction.total)}))
        elif corroboration.po_ok is False:
            detail = corroboration.outcomes.get("po")
            results.append(_result(
                "R5", version, False, Verdict.ESCALATE, "po-violation",
                f"Purchase-order check failed: {detail.detail if detail else 'unknown'}"))
        else:
            results.append(_result("R5", version, True, None, "within-cap",
                                   "Total within cap and PO authorization"))

    # R6: due date plausible.
    if extraction is None:
        results.append(_result("R6", version, False, Verdict.ESCALATE, "dates-unverifiable",
                               "Cannot evaluate dates without extraction"))
    elif extraction.due_date < extraction.issue_date:
        results.append(_result("R6", version, False, Verdict.ESCALATE, "due-before-issue",
                               "Due date is before the issue date"))
    elif (extraction.due_date - extraction.issue_date).days > settings.due_date_max_days:
        results.append(_result(
            "R6", version, False, Verdict.ESCALATE, "due-too-far",
            f"Due date exceeds {settings.due_date_max_days} days after issue"))
    else:
        results.append(_result("R6", version, True, None, "dates-plausible",
                               "Due date is plausible"))

    # R7: optional-evidence conflicts (SAM count; voice).
    if corroboration is not None and corroboration.outcomes.get("sam") is not None:
        sam = corroboration.outcomes["sam"]
        voice = corroboration.outcomes.get("voice")
        if sam.status.name == "CONFLICT":
            results.append(_result("R7", version, False, Verdict.ESCALATE, "sam-count-conflict",
                                   f"Delivery evidence conflicts: {sam.detail}"))
        elif voice is not None and voice.status.name == "CONFLICT":
            results.append(_result("R7", version, False, Verdict.ESCALATE, "voice-conflict",
                                   f"Voice evidence conflicts: {voice.detail}"))
        elif _unevaluated_lanes(sam, voice):
            lanes = ", ".join(_unevaluated_lanes(sam, voice))
            results.append(_result(
                "R7", version, True, None, "evidence-not-evaluated",
                f"Optional evidence uploaded but not evaluated ({lanes}); "
                f"no conflicts found in evaluated lanes"))
        else:
            results.append(_result("R7", version, True, None, "evidence-consistent",
                                   "No optional-evidence conflicts"))
    elif _unevaluated_lane_names(voice_lane=voice_lane, sam_lane=sam_lane):
        lanes = ", ".join(_unevaluated_lane_names(voice_lane=voice_lane,
                                                 sam_lane=sam_lane))
        results.append(_result(
            "R7", version, True, None, "evidence-not-evaluated",
            f"Optional evidence uploaded but not evaluated ({lanes}); "
            f"extraction failed so no comparison ran"))
    else:
        results.append(_result("R7", version, True, None, "evidence-consistent",
                               "No optional-evidence conflicts"))

    # R8: required fields present and schema-valid.
    if not schema_ok:
        results.append(_result("R8", version, False, Verdict.DENY, "schema-invalid",
                               f"Extraction is schema-invalid: {'; '.join(schema_errors) or 'unknown'}"))
    elif extraction is None:
        results.append(_result("R8", version, False, Verdict.DENY, "missing-extraction",
                               "No extraction available"))
    elif not extraction.bank_reference and not (
            corroboration is not None and corroboration.bank_match is not None):
        results.append(_result("R8", version, False, Verdict.DENY, "missing-bank-reference",
                               "Bank reference is required and was not provided"))
    else:
        results.append(_result("R8", version, True, None, "fields-present",
                               "Required fields present and schema-valid"))

    # R9: required verifiers executed without error.
    if required_verifier_errors:
        results.append(_result("R9", version, False, Verdict.DENY, "verifier-error",
                               f"Required verifier failed: {'; '.join(required_verifier_errors)}"))
    else:
        results.append(_result("R9", version, True, None, "verifiers-ok",
                               "Required verifiers executed without error"))

    # R10: no vendor ambiguity (fires even when R1 resolved exactly --
    # branch steering to one of two lookalikes must not auto-approve).
    if corroboration is not None and corroboration.vendor_match.ambiguous:
        results.append(_result(
            "R10", version, False, Verdict.ESCALATE, "vendor-ambiguous",
            f"{len(corroboration.vendor_match.candidates)} plausible vendors; refusing to choose"))
    else:
        results.append(_result("R10", version, True, None, "vendor-unambiguous",
                               "No vendor ambiguity"))

    return aggregate(results), results


def aggregate(results: list[RuleResult]) -> Verdict:
    """Precedence: R9/verifier errors -> DENY; R1/R2/R3/R4/R8 -> DENY;
    R5/R6/R7/R10 -> ESCALATE; else ALLOW_PROPOSAL."""
    by_id = {result.rule_id: result for result in results}
    r9 = by_id.get("R9")
    if r9 is not None and not r9.passed:
        return Verdict.DENY
    for rule_id in ("R1", "R2", "R3", "R4", "R8"):
        rule = by_id.get(rule_id)
        if rule is not None and not rule.passed:
            return Verdict.DENY
    for rule_id in ("R5", "R6", "R7", "R10"):
        rule = by_id.get(rule_id)
        if rule is not None and not rule.passed:
            return Verdict.ESCALATE
    return Verdict.ALLOW_PROPOSAL
