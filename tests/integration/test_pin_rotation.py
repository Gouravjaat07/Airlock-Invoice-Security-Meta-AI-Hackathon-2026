"""Owner PIN rotation via scripts/setup_airlock.py (supported mechanism).

Rotation rewrites only AIRLOCK_PIN_HASH in .env: the old PIN must stop
authenticating, the new PIN must work, lockout/CSRF/session behavior
must be unchanged, and every database record (vendors, bank
fingerprints, proposals, audit chain) must be intact. All secrets are
dynamic; nothing credential-shaped is hardcoded or printed.
"""

import dataclasses
import secrets

import setup_airlock


def _snapshot(conn):
    vendors = conn.execute(
        "SELECT vendor_id, name_norm, active_bank_fingerprint, status"
        " FROM vendors ORDER BY vendor_id").fetchall()
    proposals = conn.execute(
        "SELECT proposal_id, proposal_hash, status FROM proposals"
        " ORDER BY proposal_id").fetchall()
    audit = conn.execute(
        "SELECT id, event_hash FROM audit_events ORDER BY id").fetchall()
    return ([tuple(row) for row in vendors],
            [tuple(row) for row in proposals],
            [tuple(row) for row in audit])


def test_pin_rotation_recovery_flow(settings, seeded_db, test_pin, tmp_path,
                                    monkeypatch, capsys):
    import json as _json

    from app.auth.pin import verify_pin
    from app.config import override_settings
    from app.main import create_app
    from tests.asgi_harness import ASGIClient

    (tmp_path / "pyproject.toml").write_text('[project]\nname="x"\n',
                                             encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    # Old PIN authenticates before rotation.
    override_settings(settings)
    try:
        client = ASGIClient(create_app())
        first = client.post("/api/v1/auth/login", json={"pin": test_pin})
        assert first.status_code == 200, first.text
    finally:
        override_settings(None)
    vendors_before, proposals_before, audit_before = _snapshot(seeded_db)

    # Isolated env file mirroring the managed keys plus unrelated config.
    env_path = tmp_path / "rot.env"
    bank_str = settings.bank_hash_key.decode("utf-8")
    model_key = "MODEL_" + "API_KEY"
    model_val = "SYNTHETIC-ROT-" + "001"
    lines = [
        "# synthetic rotation fixture - must be preserved",
        "AIRLOCK_PIN_HASH" + "=" + settings.pin_hash,
        "AIRLOCK_SESSION_SECRET" + "=" + settings.session_secret,
        "AIRLOCK_BANK_HASH_KEY" + "=" + bank_str,
        "AIRLOCK_DB_PATH" + "=" + settings.db_path,
        "AIRLOCK_BLOB_DIR" + "=" + settings.blob_dir,
        "AIRLOCK_ENV=test",
        model_key + "=" + model_val,
        "AIRLOCK_FIXTURE_READER=1",
    ]
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Supported rotation: authorized overwrite with an injected PIN.
    new_pin = "new-pin-" + secrets.token_hex(4)
    monkeypatch.setenv("AIRLOCK_SETUP_PIN", new_pin)
    monkeypatch.delenv("AIRLOCK_SETUP_OVERWRITE", raising=False)
    rc = setup_airlock.main(["--non-interactive", "--env-file", "rot.env",
                             "--overwrite"])
    assert rc == 0
    parsed = setup_airlock._read_env_file(env_path)
    new_hash = parsed["AIRLOCK_PIN_HASH"]
    assert new_hash != settings.pin_hash
    assert parsed["AIRLOCK_SESSION_SECRET"] == settings.session_secret
    assert parsed["AIRLOCK_BANK_HASH_KEY"] == bank_str
    assert parsed["AIRLOCK_DB_PATH"] == settings.db_path
    assert parsed[model_key] == model_val
    assert verify_pin(new_hash, new_pin) is True
    assert verify_pin(new_hash, test_pin) is False
    assert new_pin not in env_path.read_text(encoding="utf-8")

    # App restarts against the rotated hash (process env never auto-loads).
    rotated = dataclasses.replace(settings, pin_hash=new_hash)
    override_settings(rotated)
    try:
        client = ASGIClient(create_app())
        old = client.post("/api/v1/auth/login", json={"pin": test_pin})
        assert old.status_code == 401
        wrong = client.post("/api/v1/auth/login",
                            json={"pin": "wrong-" + secrets.token_hex(2)})
        assert wrong.status_code == 401
        good = client.post("/api/v1/auth/login", json={"pin": new_pin})
        assert good.status_code == 200, good.text
        csrf = good.json()["csrf_token"]
        assert client.cookies.get("airlock_session")
        me = client.get("/api/v1/auth/me")
        assert me.status_code == 200
        verify = client.post("/api/v1/audit/verify", json={},
                             headers={"X-CSRF-Token": csrf})
        assert verify.status_code == 200
        assert verify.json()["ok"] is True
        # Lockout still triggers and still blocks even the correct PIN.
        for _ in range(5):
            attempt = client.post(
                "/api/v1/auth/login",
                json={"pin": "wrong-" + secrets.token_hex(2)})
            assert attempt.status_code == 401
        locked = client.post("/api/v1/auth/login",
                             json={"pin": "wrong-" + secrets.token_hex(2)})
        assert locked.status_code == 429
        denied = client.post("/api/v1/auth/login", json={"pin": new_pin})
        assert denied.status_code == 429
    finally:
        override_settings(None)

    # Every pre-rotation record is intact; only new session/audit rows exist.
    vendors_after, proposals_after, audit_after = _snapshot(seeded_db)
    assert vendors_after == vendors_before
    assert proposals_after == proposals_before
    assert [row[1] for row in audit_after[:len(audit_before)]] == [
        row[1] for row in audit_before]

    out = capsys.readouterr()
    combined = out.out + out.err + _json.dumps({})
    for secret in (test_pin, new_pin, new_hash, settings.pin_hash,
                   settings.session_secret, bank_str):
        assert secret not in combined
