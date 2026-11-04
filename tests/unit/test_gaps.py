"""Unit tests: adapters, auth primitives, eval fixtures (direct)."""

from __future__ import annotations

import sys

import pytest

from app.core.errors import AppError


def test_fixture_reader_gating(settings):
    from app.adapters.readers import FixtureReader
    settings.fixture_reader_enabled = False
    with pytest.raises(AppError) as exc_info:
        FixtureReader(settings).read(b"%PDF fake")
    assert exc_info.value.code == "E_READER_UNAVAILABLE"
    assert FixtureReader(settings).scenario_for_invoice(b"x") is None


def test_fixture_reader_unknown_and_malformed(settings, tmp_path):
    from app.adapters.readers import FixtureReader
    reader = FixtureReader(settings)
    with pytest.raises(AppError) as exc_info:
        reader.read(b"%PDF-1.4 unregistered \n%%EOF\n")
    assert exc_info.value.code == "E_READER_UNAVAILABLE"
    # Malformed scenario files are skipped, not fatal.
    (tmp_path / "scenarios").mkdir()
    (tmp_path / "scenarios" / "bad.json").write_text("{nope", encoding="utf-8")
    (tmp_path / "scenarios" / "list.json").write_text("[1]", encoding="utf-8")
    (tmp_path / "scenarios" / "noref.json").write_text("{}", encoding="utf-8")
    settings.fixtures_dir = str(tmp_path)
    with pytest.raises(AppError):
        FixtureReader(settings).read(b"whatever")


def test_fixture_reader_error_and_nondict(settings, tmp_path):
    import json
    from app.adapters.readers import FixtureReader
    root = tmp_path / "fx"
    (root / "scenarios").mkdir(parents=True)
    (root / "invoices").mkdir()
    bad_pdf = b"%PDF-1.4 bad\n%%EOF\n"
    (root / "invoices" / "bad.pdf").write_bytes(bad_pdf)
    (root / "scenarios" / "bad.json").write_text(json.dumps({
        "name": "bad", "invoice_artifact": "invoices/bad.pdf",
        "extraction": [1, 2, 3]}))
    (root / "scenarios" / "missing.json").write_text(json.dumps({
        "name": "missing", "invoice_artifact": "invoices/nope.pdf",
        "extraction": {}}))
    settings.fixtures_dir = str(root)
    reader = FixtureReader(settings)
    with pytest.raises(AppError) as exc_info:
        reader.read(bad_pdf)
    assert exc_info.value.code == "E_SCHEMA"
    spec = reader.scenario_for_invoice(bad_pdf)
    assert spec is not None and spec["name"] == "bad"


def test_reader_timeout_fixture(settings):
    from tests.conftest import fixture_bytes
    from app.adapters.readers import FixtureReader
    with pytest.raises(AppError) as exc_info:
        FixtureReader(settings).read(
            fixture_bytes("invoices/reader-timeout.pdf"))
    assert exc_info.value.code == "E_READER_TIMEOUT"


def test_sam_direct_errors(settings, tmp_path):
    from app.adapters.vision import MockSam
    settings.fixture_reader_enabled = False
    with pytest.raises(AppError):
        MockSam(settings).count(b"x", catalogue_item_id="i",
                                catalogue_label="L")
    settings.fixture_reader_enabled = True
    settings.fixtures_dir = str(tmp_path)  # no scenarios dir
    with pytest.raises(AppError):
        MockSam(settings).count(b"x", catalogue_item_id="i",
                                catalogue_label="L")


def test_sam_range_and_record(settings):
    from tests.conftest import fixture_bytes
    from app.adapters.vision import MockSam
    sam = MockSam(settings)
    settings.sam_count_min = 100
    with pytest.raises(AppError):
        sam.count(fixture_bytes("delivery/sam-ok.png"),
                  catalogue_item_id="flour-25kg",
                  catalogue_label="Flour sack 25kg")
    settings.sam_count_min = 0
    evidence = sam.count(fixture_bytes("delivery/sam-ok.png"),
                         catalogue_item_id="flour-25kg",
                         catalogue_label="Flour sack 25kg")
    record = sam.evidence_record(evidence)
    assert record["count"] == 30 and "limitations" in record


def test_asr_direct_errors(settings, tmp_path):
    from tests.conftest import fixture_bytes
    from app.adapters.transcription import MockAsr
    settings.fixture_reader_enabled = False
    with pytest.raises(AppError):
        MockAsr(settings).transcribe(b"x")
    settings.fixture_reader_enabled = True
    with pytest.raises(AppError):
        MockAsr(settings).transcribe(b"not-a-fixture")
    result = MockAsr(settings).transcribe(
        fixture_bytes("voice/voice-instruction.wav"))
    assert "Ignore" in result.text


def test_pin_without_argon2(monkeypatch):
    from app.auth import pin as pin_mod
    monkeypatch.setitem(sys.modules, "argon2", None)
    with pytest.raises(RuntimeError):
        pin_mod.hash_pin("valid-pin")
    with pytest.raises(ValueError):
        pin_mod.hash_pin("abc")
    assert pin_mod.verify_pin("whatever", "pin") is False
    assert pin_mod.verify_pin(None, "pin") is False
    assert pin_mod.verify_pin("x", "") is False


def test_pin_roundtrip():
    pytest.importorskip("argon2")
    from app.auth.pin import hash_pin, verify_pin
    hashed = hash_pin("correct-horse")
    assert verify_pin(hashed, "correct-horse") is True
    assert verify_pin(hashed, "wrong") is False
    assert verify_pin("not-a-hash", "x") is False


def test_rate_limit_windows(seeded_db):
    from app.auth import rate_limit
    conn = seeded_db
    assert rate_limit.is_locked(conn, "k", limit=2,
                               window_seconds=60) is False
    assert rate_limit.check_and_hit(conn, "k", limit=2,
                                   window_seconds=60)[0] is True
    assert rate_limit.check_and_hit(conn, "k", limit=2,
                                   window_seconds=60)[0] is True
    allowed, retry = rate_limit.check_and_hit(conn, "k", limit=2,
                                              window_seconds=60)
    assert allowed is False and retry >= 1
    assert rate_limit.is_locked(conn, "k", limit=2,
                               window_seconds=60) is True
    rate_limit.clear(conn, "k")
    assert rate_limit.is_locked(conn, "k", limit=2,
                               window_seconds=60) is False
    # Expired window resets.
    conn.execute("INSERT INTO rate_limits (scope_key, window_start, count)"
                 " VALUES ('k2','2000-01-01T00:00:00+00:00',99)")
    assert rate_limit.check_and_hit(conn, "k2", limit=2,
                                   window_seconds=60)[0] is True
    assert rate_limit.is_locked(conn, "k2", limit=2,
                               window_seconds=60) is False
    assert rate_limit.lockout_until("k", window_seconds=60) is not None


def test_challenges_mismatch_and_reuse(seeded_db, settings):
    from app.auth import challenges
    from app.core.security import hash_token
    from app.storage.database import transaction
    conn = seeded_db
    with transaction(conn):
        from app.storage.repositories import SessionRepository
        SessionRepository().create(conn, session_id="s1",
                                   token_hash="t", csrf_hash="c",
                                   now="t", expires_at="2999-01-01T00:00:00+00:00")
    challenge = challenges.issue(conn, settings, proposal_hash="h1",
                                 session_id="s1")
    row = challenges.load_valid(conn, challenge, proposal_hash="h1",
                                session_id="s1")
    # Regression (F2): only the hash is stored, never the raw bearer.
    assert row["challenge_hash"] == hash_token(challenge)
    assert row["challenge_hash"] != challenge
    with pytest.raises(AppError):
        challenges.load_valid(conn, challenge, proposal_hash="other",
                              session_id="s1")
    with pytest.raises(AppError):
        challenges.load_valid(conn, challenge, proposal_hash="h1",
                              session_id="s2")
    with pytest.raises(AppError):
        challenges.load_valid(conn, "ch-missing", proposal_hash="h1",
                              session_id="s1")
    with transaction(conn):
        challenges.consume(conn, challenge)
    with pytest.raises(AppError):
        with transaction(conn):
            challenges.consume(conn, challenge)
    with pytest.raises(AppError):
        challenges.load_valid(conn, challenge, proposal_hash="h1",
                              session_id="s1")
    conn.execute("INSERT INTO auth_challenges (challenge_hash, proposal_hash,"
                 " session_id, created_at, expires_at) VALUES (?,?,"
                 " 's1','t','2000-01-01T00:00:00+00:00')",
                 (hash_token("ch-old"), "h1"))
    with pytest.raises(AppError) as exc_info:
        challenges.load_valid(conn, "ch-old", proposal_hash="h1",
                              session_id="s1")
    assert exc_info.value.code == "E_EXPIRED"


def test_sessions_failures(seeded_db, settings):
    from app.auth import sessions
    from app.auth.sessions import validate_csrf
    from app.storage.database import transaction
    conn = seeded_db
    with pytest.raises(AppError):
        sessions.validate_session(conn, settings, None)
    with pytest.raises(AppError):
        sessions.validate_session(conn, settings, "bogus-token")
    with transaction(conn):
        from app.storage.repositories import SessionRepository
        SessionRepository().create(conn, session_id="s9",
                                   token_hash="h" * 64, csrf_hash="c" * 64,
                                   now="t",
                                   expires_at="2999-01-01T00:00:00+00:00")
    sessions.logout(conn, "s9")
    with pytest.raises(AppError):
        sessions.validate_session(conn, settings, "x" * 10)
    with pytest.raises(AppError) as exc_info:
        validate_csrf({"csrf_hash": "h"}, "wrong", via_cookie=True)
    assert exc_info.value.status == 403
    validate_csrf({"csrf_hash": "h"}, None, via_cookie=False)


def test_eval_fixture_errors(settings, tmp_path):
    from app.evaluation import fixtures as fixture_io
    with pytest.raises(AppError):
        fixture_io.load_scenario(settings, "../evil")
    with pytest.raises(AppError):
        fixture_io.load_scenario(settings, "no-such-scenario")
    with pytest.raises(AppError):
        fixture_io.read_artifact_bytes(settings, "../../pyproject.toml")
    with pytest.raises(AppError):
        fixture_io.read_artifact_bytes(settings, "invoices/missing.pdf")
    settings.fixtures_dir = str(tmp_path)
    assert fixture_io.list_scenarios(settings) == []
    bad = tmp_path / "scenarios"
    bad.mkdir()
    (bad / "v1.json").write_text('{"attack_id": "A01"}',
                                 encoding="utf-8")
    with pytest.raises(AppError):
        fixture_io.load_scenario(settings, "v1")
    (bad / "verdict.json").write_text(
        '{"attack_type": "A99", "expected_verdict": "MAYBE"}',
        encoding="utf-8")
    with pytest.raises(AppError):
        fixture_io.load_scenario(settings, "verdict")
    (bad / "notobj.json").write_text('[1]', encoding="utf-8")
    with pytest.raises(AppError):
        fixture_io.load_scenario(settings, "notobj")
    (bad / "unreadable.json").write_text('{bad', encoding="utf-8")
    with pytest.raises(AppError):
        fixture_io.load_scenario(settings, "unreadable")


def test_policy_eval_errors(seeded_db, settings, store):
    from app.evaluation import policy_eval
    settings.enable_eval_api = False
    with pytest.raises(AppError) as exc_info:
        policy_eval.run_scenarios(seeded_db, settings, store, ["clean"])
    assert exc_info.value.code == "E_AUTH"
    settings.enable_eval_api = True
    with pytest.raises(AppError):
        policy_eval.get_run(seeded_db, "run-missing")


def test_eval_false_allow_counts_only_reject_expected():
    from phase3_eval import is_false_allow
    attack_deny = {"attack_type": "A01", "expected_verdict": "DENY"}
    assert is_false_allow(attack_deny, "ALLOW_PROPOSAL") is True
    assert is_false_allow(attack_deny, "DENY") is False
    attack_escalate = {"attack_type": "A09", "expected_verdict": "ESCALATE"}
    assert is_false_allow(attack_escalate, "ALLOW_PROPOSAL") is True
    # Attack samples proving injection-inertness (expected ALLOW)
    # must never count: the valid values decided, the hostile text
    # stayed data.
    attack_allow = {"attack_type": "A01",
                    "expected_verdict": "ALLOW_PROPOSAL"}
    assert is_false_allow(attack_allow, "ALLOW_PROPOSAL") is False
    assert is_false_allow({"expected_verdict": "DENY"},
                          "ALLOW_PROPOSAL") is False
    assert is_false_allow(attack_deny, "ERROR:E_X") is False


def test_eval_reader_timeout_matches_injected_error(seeded_db, settings,
                                                    store):
    from app.evaluation import policy_eval
    report = policy_eval.run_scenarios(seeded_db, settings, store,
                                       ["reader-timeout"])
    (item,) = report["results"]
    assert item["actual"] == "ERROR:E_READER_TIMEOUT"
    assert item["expected"] == "DENY"
    assert item["match"] is True
    assert item["proposal"] is False
    assert item["case_id"] is not None


@pytest.mark.parametrize("scenario", ["hidden-text", "injection-visible",
                                      "planner-injection"])
def test_eval_injection_scenarios_allow_with_inert_text(seeded_db, settings,
                                                        store, scenario):
    import json as _json
    from app.core.security import bank_fingerprint
    from app.evaluation import policy_eval
    report = policy_eval.run_scenarios(seeded_db, settings, store, [scenario])
    (item,) = report["results"]
    assert item["actual"] == "ALLOW_PROPOSAL"
    assert item["expected"] == "ALLOW_PROPOSAL"
    assert item["match"] is True
    rows = seeded_db.execute(
        "SELECT field, value_json, taint_class FROM facts WHERE case_id = ?",
        (item["case_id"],)).fetchall()
    facts = {row["field"]: row for row in rows}
    bank = _json.loads(facts["bank"]["value_json"])
    assert bank["fingerprint"] == bank_fingerprint("SYN-ACME-0001",
                                                  settings.bank_hash_key)
    assert bank["match"] is True
    assert facts["bank"]["taint_class"] == "T2"
    items = _json.loads(facts["line_items"]["value_json"])
    assert facts["line_items"]["taint_class"] == "T2"
    if scenario != "hidden-text":
        # Hostile text flows through as preserved T2 data — quoted,
        # never obeyed.
        assert any("IGNORE" in entry["description"]
                   or "SYSTEM" in entry["description"] for entry in items)
