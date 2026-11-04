"""Unit tests: state machine, normalization, fingerprints, explainer."""

from __future__ import annotations

import pytest

from app.core.errors import AppError
from app.core.security import bank_fingerprint, normalize_bank_reference
from app.domain.enums import CaseState, Verdict
from app.domain.vendors import normalize_vendor_name
from app.pipeline.registry import levenshtein_cutoff
from app.pipeline.state_machine import TRANSITIONS, check_transition


def test_all_states_have_defined_transitions():
    assert set(TRANSITIONS) == set(CaseState)


def test_happy_path_transitions():
    for current, nxt in [(CaseState.UPLOADED, CaseState.READING),
                         (CaseState.READING, CaseState.CORROBORATING),
                         (CaseState.CORROBORATING, CaseState.VERDICT),
                         (CaseState.VERDICT, CaseState.PROPOSED),
                         (CaseState.PROPOSED, CaseState.CONFIRMED),
                         (CaseState.CONFIRMED, CaseState.EXECUTED)]:
        check_transition(current, nxt)


def test_illegal_transitions_rejected():
    with pytest.raises(AppError):
        check_transition(CaseState.UPLOADED, CaseState.EXECUTED)
    with pytest.raises(AppError):
        check_transition(CaseState.EXECUTED, CaseState.READING)
    with pytest.raises(AppError):
        check_transition(CaseState.REJECTED, CaseState.PROPOSED)
    with pytest.raises(AppError):
        check_transition(CaseState.CANCELLED, CaseState.READING)


def test_terminal_states_have_no_exits():
    assert TRANSITIONS[CaseState.EXECUTED] == frozenset()
    assert TRANSITIONS[CaseState.CANCELLED] == frozenset()


def test_normalize_vendor_name():
    assert normalize_vendor_name("  Acme   Flour CO. ") == "acme flour co"
    assert normalize_vendor_name("HARBOR OVENS LTD") == "harbor ovens ltd"
    assert normalize_vendor_name("Café\u00a0Supplies") == "café supplies"


def test_levenshtein_cutoff():
    assert levenshtein_cutoff("abc", "abc", 2) == 0
    assert levenshtein_cutoff("abc", "abd", 2) == 1
    assert levenshtein_cutoff("abc", "abcdefgh", 2) > 2
    assert levenshtein_cutoff("harbor ovens ltd", "harbor oven ltd", 2) == 1


def test_bank_fingerprint_keyed_and_normalized():
    key = b"test-key-123"
    assert bank_fingerprint("SYN-001", key) == bank_fingerprint("syn 001", key)
    assert bank_fingerprint("SYN-001", key) != bank_fingerprint("SYN-002", key)
    assert bank_fingerprint("SYN-001", key) != bank_fingerprint("SYN-001", b"other")
    assert bank_fingerprint("SYN-001", key).startswith("v1:")
    with pytest.raises(ValueError):
        bank_fingerprint("SYN-001", b"")
    with pytest.raises(ValueError):
        bank_fingerprint("   ", key)


def test_normalize_bank_reference():
    assert normalize_bank_reference("syn- 001") == "SYN001"


def test_template_explainer_only_uses_verdict_and_rules():
    from app.adapters.explanations import TemplateExplainer
    from app.domain.verdicts import RuleResult
    rules = [RuleResult(rule_id="R1", rule_version="2.0.0", passed=True,
                        outcome=None, reason_code="ok", message="fine"),
             RuleResult(rule_id="R2", rule_version="2.0.0", passed=False,
                        outcome=Verdict.DENY, reason_code="bank-mismatch",
                        message="Bank mismatch")]
    text = TemplateExplainer().explain(Verdict.DENY, rules)
    assert "DENY" in text and "R1" in text and "bank-mismatch" in text
    assert "approve all payments" not in text.lower()


def test_audit_hash_chain_roundtrip(seeded_db):
    from app.services import audit_service
    from app.storage.database import transaction
    with transaction(seeded_db):
        audit_service.record(seeded_db, "case.created", case_id="c1",
                             payload={"files": 1})
        audit_service.record(seeded_db, "verdict.created", case_id="c1",
                             payload={"verdict": "DENY"})
    result = audit_service.verify_chain(seeded_db)
    assert result == {"ok": True, "events": 2, "break_at": None,
                      "reason": None}


def test_audit_triggers_block_update_and_delete(seeded_db):
    import sqlite3
    from app.services import audit_service
    from app.storage.database import transaction
    with transaction(seeded_db):
        audit_service.record(seeded_db, "case.created", payload={})
    with pytest.raises(sqlite3.Error):
        seeded_db.execute("UPDATE audit_events SET payload_json='{}' WHERE id=1")
    with pytest.raises(sqlite3.Error):
        seeded_db.execute("DELETE FROM audit_events WHERE id=1")
