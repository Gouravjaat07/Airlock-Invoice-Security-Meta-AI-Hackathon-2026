"""Adversarial tests: injection fixtures A01-A16 mapped to behavior."""

from __future__ import annotations

import json

import pytest

from app.evaluation import fixtures as fixture_io
from app.services import case_service
from tests.conftest import ROOT_DIR

# scenario -> (expected verdict, rules that must/must-not fire)
EXPECTATIONS = {
    "clean": ("ALLOW_PROPOSAL", []),
    "changed-bank": ("DENY", ["R2"]),
    "arithmetic-mismatch": ("DENY", ["R3"]),
    "over-cap": ("ESCALATE", ["R5"]),
    "invalid-due": ("ESCALATE", ["R6"]),
    "ambiguous-vendor": ("ESCALATE", ["R10"]),
    "lookalike-vendor": ("DENY", ["R1"]),
    "sam-conflict": ("ESCALATE", ["R7"]),
    "sam-ok": ("ALLOW_PROPOSAL", []),
    "missing-field": ("DENY", ["R8"]),
    "malformed-reader": ("DENY", ["R8"]),
    "injection-visible": ("ALLOW_PROPOSAL", []),
    "hidden-text": ("ALLOW_PROPOSAL", []),
    "voice-instruction": ("ESCALATE", ["R7"]),
    "planner-injection": ("ALLOW_PROPOSAL", []),
    "verifier-timeout": ("DENY", ["R9"]),
    "po-exceeded": ("ESCALATE", ["R5"]),
}


def _process(seeded_db, settings, store, name):
    spec = fixture_io.load_scenario(settings, name)
    files = [("invoice", "inv.pdf",
              fixture_io.read_artifact_bytes(settings,
                                             spec["invoice_artifact"]))]
    if spec.get("delivery_artifact"):
        files.append(("delivery", "del.png",
                      fixture_io.read_artifact_bytes(
                          settings, spec["delivery_artifact"])))
    if spec.get("voice_artifact"):
        files.append(("voice", "v.wav",
                      fixture_io.read_artifact_bytes(
                          settings, spec["voice_artifact"])))
    created = case_service.create_case(seeded_db, settings, store, files)
    return case_service.process_case(seeded_db, settings, store,
                                     created["case"]["id"])


@pytest.mark.parametrize("name", sorted(EXPECTATIONS))
def test_scenario_verdicts(seeded_db, settings, store, name):
    expected, must_fire = EXPECTATIONS[name]
    summary = _process(seeded_db, settings, store, name)
    assert summary["verdict"]["verdict"] == expected, name
    fired = json.loads(summary["verdict"]["rule_ids_json"])
    for rule_id in must_fire:
        assert rule_id in fired, f"{name}: {rule_id} did not fire"
    if expected == "ALLOW_PROPOSAL":
        assert summary["proposal"] is not None
    else:
        assert summary["proposal"] is None


def test_injection_text_stays_inert(seeded_db, settings, store):
    summary = _process(seeded_db, settings, store, "injection-visible")
    assert summary["verdict"]["verdict"] == "ALLOW_PROPOSAL"
    # The injected bank reference never became the proposal payee data.
    assert summary["proposal"]["vendor_id"] == "ven-acme-flour"
    assert summary["proposal"]["amount"] == "1240.00"


def test_planner_text_never_leaks_into_explanation(seeded_db, settings,
                                                   store):
    summary = _process(seeded_db, settings, store, "planner-injection")
    assert summary["verdict"]["verdict"] == "ALLOW_PROPOSAL"
    assert "SYSTEM" not in (summary["explanation"] or "")
    assert "payment approver" not in (summary["explanation"] or "")


def test_facts_remain_tainted(seeded_db, settings, store):
    summary = _process(seeded_db, settings, store, "injection-visible")
    taints = {fact["taint_class"] for fact in summary["facts"]}
    assert taints == {"T2"}


def test_duplicate_after_clean_denies(seeded_db, settings, store):
    _process(seeded_db, settings, store, "clean")
    summary = _process(seeded_db, settings, store, "duplicate")
    assert summary["verdict"]["verdict"] == "DENY"
    assert "R4" in json.loads(summary["verdict"]["rule_ids_json"])


def test_manifest_v2_vocabulary_preserved(settings):
    spec = fixture_io.load_scenario(settings, "changed-bank")
    assert spec["attack_type"] == "A08"
    assert "attack_id" not in spec
    template = json.loads(
        (ROOT_DIR / "eval" / "manifest.dev.template.json").read_text())
    assert template["manifest_version"] == "2.0.0"
