"""Unit tests: deterministic policy R1-R10 (positive/negative/boundary)."""

from __future__ import annotations

import copy
import datetime as dt


from app.domain.enums import Verdict
from app.pipeline import policy
from app.pipeline.corroborate import corroborate
from app.pipeline.registry import resolve_vendor
from app.pipeline.validate import validate_extraction

BASE = {
    "vendor_name": "Acme Flour Co",
    "invoice_number": "INV-2026-0001",
    "issue_date": "2026-10-01",
    "due_date": "2026-10-31",
    "currency": "USD",
    "subtotal": "1200.00",
    "tax": "40.00",
    "total": "1240.00",
    "bank_reference": "SYN-ACME-0001",
    "po_reference": "PO-1001",
    "line_items": [
        {"description": "Flour sack 25kg", "quantity": "10",
         "unit_price": "100.00"},
        {"description": "Yeast pack 500g", "quantity": "20",
         "unit_price": "10.00"},
    ],
}


def run(seeded_db, settings, payload, **corr_kwargs):
    extraction = validate_extraction(copy.deepcopy(payload))
    match = resolve_vendor(seeded_db, extraction.vendor_name)
    corr = corroborate(seeded_db, settings, extraction, match, **corr_kwargs)
    verdict, rules = policy.evaluate_policy(
        settings, extraction, corr, schema_ok=True,
        required_verifier_errors=list(corr.verifier_errors))
    by_id = {rule.rule_id: rule for rule in rules}
    return verdict, by_id, corr


def failed_rules(by_id):
    return sorted(rule_id for rule_id, rule in by_id.items() if not rule.passed)


def test_clean_allows(seeded_db, settings):
    verdict, by_id, _ = run(seeded_db, settings, BASE)
    assert verdict == Verdict.ALLOW_PROPOSAL
    assert failed_rules(by_id) == []
    assert all(rule.rule_version == settings.policy_version
               for rule in by_id.values())


def test_r1_unknown_vendor_denies(seeded_db, settings):
    payload = dict(BASE, vendor_name="Nonexistent Corp")
    verdict, by_id, _ = run(seeded_db, settings, payload)
    assert verdict == Verdict.DENY
    assert "R1" in failed_rules(by_id)


def test_r1_normalized_match_resolves(seeded_db, settings):
    payload = dict(BASE, vendor_name="  ACME flour   CO!! ")
    verdict, by_id, _ = run(seeded_db, settings, payload)
    assert verdict == Verdict.ALLOW_PROPOSAL


def test_r1_fuzzy_does_not_resolve(seeded_db, settings):
    payload = dict(BASE, vendor_name="Acme Flower Co")  # 1 edit, plausible only
    verdict, by_id, corr = run(seeded_db, settings, payload)
    assert corr.vendor_match.vendor is None
    assert verdict == Verdict.DENY
    assert "R1" in failed_rules(by_id)


def test_r2_wrong_bank_denies(seeded_db, settings):
    payload = dict(BASE, bank_reference="SYN-ATTACKER-9999")
    verdict, by_id, _ = run(seeded_db, settings, payload)
    assert verdict == Verdict.DENY
    assert failed_rules(by_id) == ["R2"]


def test_r2_fingerprint_compare_is_constant_time(seeded_db, settings,
                                                     monkeypatch):
    """Regression (F5): bank fingerprints use constant-time comparison."""
    import app.pipeline.corroborate as corr_mod
    calls = []
    real = corr_mod.constant_time_equal

    def _spy(first, second):
        calls.append((first, second))
        return real(first, second)
    monkeypatch.setattr(corr_mod, "constant_time_equal", _spy)
    verdict, _, _ = run(seeded_db, settings, BASE)
    assert verdict == Verdict.ALLOW_PROPOSAL
    assert calls, "bank comparison must go through constant_time_equal"
    assert all(first.startswith("v1:") for first, _ in calls)


def test_r2_missing_key_fails_closed(seeded_db, settings):
    settings.bank_hash_key = None
    verdict, by_id, corr = run(seeded_db, settings, BASE)
    assert corr.verifier_errors
    assert verdict == Verdict.DENY
    assert "R9" in failed_rules(by_id)


def test_r3_cent_mismatch_denies(seeded_db, settings):
    payload = dict(BASE, total="1240.01")
    verdict, by_id, _ = run(seeded_db, settings, payload)
    assert verdict == Verdict.DENY
    assert "R3" in failed_rules(by_id)


def test_r3_line_sum_mismatch_denies(seeded_db, settings):
    payload = copy.deepcopy(BASE)
    payload["line_items"][0]["quantity"] = "11"
    verdict, by_id, _ = run(seeded_db, settings, payload)
    assert verdict == Verdict.DENY
    assert "R3" in failed_rules(by_id)


def test_r4_duplicate_denies(seeded_db, settings):
    from app.pipeline.corroborate import duplicate_key
    from app.storage.database import transaction
    from app.storage.repositories import CaseRepository, InvoiceIndexRepository
    with transaction(seeded_db):
        CaseRepository().create(seeded_db, case_id="case-seed",
                                state="PROPOSED", now="t",
                                idempotency_key=None)
    extraction = validate_extraction(copy.deepcopy(BASE))
    key = duplicate_key(vendor_id="ven-acme-flour",
                        invoice_number=extraction.invoice_number,
                        total=extraction.total, issue_date=extraction.issue_date,
                        precision=settings.currency_precision)
    with transaction(seeded_db):
        InvoiceIndexRepository().insert(
            seeded_db, dup_key=key, vendor_id="ven-acme-flour",
            case_id="case-seed", number_norm="INV-2026-0001",
            total="1240.00", issue_date="2026-10-01", status="proposed",
            now="2026-10-31T00:00:00+00:00")
    verdict, by_id, _ = run(seeded_db, settings, BASE)
    assert verdict == Verdict.DENY
    assert "R4" in failed_rules(by_id)


def test_r4_distinct_number_passes(seeded_db, settings):
    payload = dict(BASE, invoice_number="INV-2026-9999")
    verdict, _, _ = run(seeded_db, settings, payload)
    assert verdict == Verdict.ALLOW_PROPOSAL


def test_r4_unicode_lookalike_is_duplicate(seeded_db, settings):
    """Regression (F4): fullwidth digits collapse to the same R4 key."""
    from app.pipeline.corroborate import duplicate_key
    from app.pipeline.registry import normalize_invoice_number
    from app.storage.database import transaction
    from app.storage.repositories import CaseRepository, InvoiceIndexRepository
    assert normalize_invoice_number("INV-2026-0001") == \
        normalize_invoice_number("ＩＮＶ-2026-0001")
    with transaction(seeded_db):
        CaseRepository().create(seeded_db, case_id="case-seed",
                                state="PROPOSED", now="t",
                                idempotency_key=None)
    extraction = validate_extraction(copy.deepcopy(BASE))
    key = duplicate_key(vendor_id="ven-acme-flour",
                        invoice_number=extraction.invoice_number,
                        total=extraction.total, issue_date=extraction.issue_date,
                        precision=settings.currency_precision)
    with transaction(seeded_db):
        InvoiceIndexRepository().insert(
            seeded_db, dup_key=key, vendor_id="ven-acme-flour",
            case_id="case-seed", number_norm="INV-2026-0001",
            total="1240.00", issue_date="2026-10-01", status="proposed",
            now="2026-10-31T00:00:00+00:00")
    payload = dict(BASE, invoice_number="ＩＮＶ-2026-0001")
    verdict, by_id, _ = run(seeded_db, settings, payload)
    assert verdict == Verdict.DENY
    assert "R4" in failed_rules(by_id)


def test_r5_at_cap_passes_over_cap_escalates(seeded_db, settings):
    at_cap = copy.deepcopy(BASE)
    at_cap.update(subtotal="10000.00", tax="0.00", total="10000.00",
                  po_reference=None,
                  line_items=[{"description": "x", "quantity": "1",
                               "unit_price": "10000.00"}])
    verdict, _, _ = run(seeded_db, settings, at_cap)
    assert verdict == Verdict.ALLOW_PROPOSAL
    over = copy.deepcopy(at_cap)
    over.update(subtotal="10000.01", total="10000.01",
                line_items=[{"description": "x", "quantity": "1",
                             "unit_price": "10000.01"}])
    verdict, by_id, _ = run(seeded_db, settings, over)
    assert verdict == Verdict.ESCALATE
    assert failed_rules(by_id) == ["R5"]


def test_r5_unknown_po_escalates(seeded_db, settings):
    payload = dict(BASE, po_reference="PO-NOPE")
    verdict, by_id, _ = run(seeded_db, settings, payload)
    assert verdict == Verdict.ESCALATE
    assert "R5" in failed_rules(by_id)


def test_r5_exceeded_po_escalates(seeded_db, settings):
    payload = dict(BASE, po_reference="PO-1002")  # remaining 100.00
    verdict, by_id, _ = run(seeded_db, settings, payload)
    assert verdict == Verdict.ESCALATE
    assert "R5" in failed_rules(by_id)


def test_r5_closed_po_escalates(seeded_db, settings):
    payload = dict(BASE, po_reference="PO-1099")
    verdict, by_id, _ = run(seeded_db, settings, payload)
    assert verdict == Verdict.ESCALATE
    assert "R5" in failed_rules(by_id)


def test_r6_boundaries(seeded_db, settings):
    same_day = dict(BASE, due_date="2026-10-01")
    verdict, _, _ = run(seeded_db, settings, same_day)
    assert verdict == Verdict.ALLOW_PROPOSAL
    max_day = dict(BASE, due_date="2026-12-30")  # issue + 90
    verdict, _, _ = run(seeded_db, settings, max_day)
    assert verdict == Verdict.ALLOW_PROPOSAL
    limit = (dt.date(2026, 10, 1) + dt.timedelta(days=120)).isoformat()
    verdict, _, _ = run(seeded_db, settings, dict(BASE, due_date=limit))
    assert verdict == Verdict.ALLOW_PROPOSAL
    over = (dt.date(2026, 10, 1) + dt.timedelta(days=121)).isoformat()
    verdict, by_id, _ = run(seeded_db, settings, dict(BASE, due_date=over))
    assert verdict == Verdict.ESCALATE
    assert "R6" in failed_rules(by_id)
    before = dict(BASE, due_date="2026-09-30")
    verdict, by_id, _ = run(seeded_db, settings, before)
    assert verdict == Verdict.ESCALATE
    assert "R6" in failed_rules(by_id)


def test_r7_absent_passes_conflict_escalates(seeded_db, settings):
    verdict, _, _ = run(seeded_db, settings, BASE)
    assert verdict == Verdict.ALLOW_PROPOSAL
    verdict, by_id, _ = run(seeded_db, settings, BASE, sam_count=30,
                            sam_item_tolerance=1)
    assert verdict == Verdict.ALLOW_PROPOSAL
    verdict, by_id, _ = run(seeded_db, settings, BASE, sam_count=5,
                            sam_item_tolerance=1)
    assert verdict == Verdict.ESCALATE
    assert "R7" in failed_rules(by_id)


def test_r7_voice_conflict_escalates(seeded_db, settings):
    verdict, by_id, _ = run(seeded_db, settings, BASE, voice_conflicts=True)
    assert verdict == Verdict.ESCALATE
    assert "R7" in failed_rules(by_id)


def test_r8_missing_bank_denies(seeded_db, settings):
    payload = copy.deepcopy(BASE)
    del payload["bank_reference"]
    verdict, by_id, _ = run(seeded_db, settings, payload)
    assert verdict == Verdict.DENY
    assert "R8" in failed_rules(by_id)


def test_r8_schema_invalid_denies(seeded_db, settings):
    verdict, rules = policy.evaluate_policy(
        settings, None, None, schema_ok=False,
        schema_errors=["total is required"])
    by_id = {rule.rule_id: rule for rule in rules}
    assert verdict == Verdict.DENY
    assert "R8" in failed_rules(by_id)


def test_r9_verifier_error_denies(seeded_db, settings):
    verdict, by_id, _ = run(seeded_db, settings, BASE,
                            sam_error="adapter exploded")
    # sam_error without sam_required is recorded but R9 needs required list;
    # pass it explicitly as a required-verifier failure:
    extraction = validate_extraction(copy.deepcopy(BASE))
    match = resolve_vendor(seeded_db, extraction.vendor_name)
    from app.pipeline.corroborate import corroborate as _corr
    corr = _corr(seeded_db, settings, extraction, match)
    verdict, rules = policy.evaluate_policy(
        settings, extraction, corr, schema_ok=True,
        required_verifier_errors=["sam-verifier: adapter exploded"])
    by_id = {rule.rule_id: rule for rule in rules}
    assert verdict == Verdict.DENY
    assert "R9" in failed_rules(by_id)


def test_r10_lookalike_pair_escalates(seeded_db, settings):
    payload = copy.deepcopy(BASE)
    payload.update(vendor_name="Harbor Ovens Ltd",
                   bank_reference="SYN-HARBOR-0002", po_reference=None,
                   invoice_number="INV-2026-0006")
    verdict, by_id, corr = run(seeded_db, settings, payload)
    assert corr.vendor_match.vendor is not None  # R1 resolved exactly
    assert corr.vendor_match.ambiguous
    assert verdict == Verdict.ESCALATE
    assert failed_rules(by_id) == ["R10"]


def test_deny_beats_escalate(seeded_db, settings):
    payload = dict(BASE, bank_reference="SYN-ATTACKER-9999",
                   due_date="2026-09-01")
    verdict, by_id, _ = run(seeded_db, settings, payload)
    assert verdict == Verdict.DENY
    assert set(failed_rules(by_id)) == {"R2", "R6"}


def test_all_rules_evaluated_despite_early_failure(seeded_db, settings):
    payload = dict(BASE, vendor_name="Nobody", bank_reference="bogus")
    verdict, by_id, _ = run(seeded_db, settings, payload)
    assert verdict == Verdict.DENY
    assert len(by_id) == 10  # every rule returned a result
    assert set(failed_rules(by_id)) == {"R1", "R2", "R4"}


def test_aggregate_precedence_unit():
    from app.domain.verdicts import RuleResult
    def rule(rule_id, passed):
        return RuleResult(rule_id=rule_id, rule_version="2.0.0",
                          passed=passed,
                          outcome=None if passed else Verdict.DENY,
                          reason_code="x", message="x")
    ids = ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9", "R10"]
    assert policy.aggregate([rule(i, True) for i in ids]) == Verdict.ALLOW_PROPOSAL
    deny = [rule(i, i != "R3") for i in ids]
    assert policy.aggregate(deny) == Verdict.DENY
    esc = [rule(i, i != "R6") for i in ids]
    assert policy.aggregate(esc) == Verdict.ESCALATE
    mixed = [rule(i, i not in ("R2", "R5")) for i in ids]
    assert policy.aggregate(mixed) == Verdict.DENY
