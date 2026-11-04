"""Repository layer: parameterized SQL behind small typed helpers.

Every method takes an explicit connection owned by the caller (one per
request/unit of work). Multi-record mutations run inside
`app.storage.database.transaction` at the service layer.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any


def _row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


class CaseRepository:
    def create(self, conn: sqlite3.Connection, *, case_id: str, state: str,
               now: str, idempotency_key: str | None) -> None:
        conn.execute(
            "INSERT INTO cases (id, state, created_at, updated_at, idempotency_key, version)"
            " VALUES (?, ?, ?, ?, ?, 1)",
            (case_id, state, now, now, idempotency_key))

    def get(self, conn: sqlite3.Connection, case_id: str) -> dict | None:
        return _row_to_dict(
            conn.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone())

    def get_by_idempotency(self, conn: sqlite3.Connection, key: str) -> dict | None:
        return _row_to_dict(
            conn.execute("SELECT * FROM cases WHERE idempotency_key = ?", (key,)).fetchone())

    def list(self, conn: sqlite3.Connection, *, limit: int, offset: int) -> list[dict]:
        rows = conn.execute(
            "SELECT * FROM cases ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset)).fetchall()
        return [dict(row) for row in rows]

    def count_by_state(self, conn: sqlite3.Connection) -> dict[str, int]:
        rows = conn.execute(
            "SELECT state, COUNT(*) FROM cases GROUP BY state").fetchall()
        return {str(state): int(count) for state, count in rows}

    def update_state(self, conn: sqlite3.Connection, *, case_id: str, state: str,
                     now: str, expected_version: int,
                     error_code: str | None = None,
                     error_summary: str | None = None) -> bool:
        """Optimistic-lock state update; False when version mismatched."""
        cursor = conn.execute(
            "UPDATE cases SET state = ?, updated_at = ?, version = version + 1,"
            " error_code = ?, error_summary = ?"
            " WHERE id = ? AND version = ?",
            (state, now, error_code, error_summary, case_id, expected_version))
        return cursor.rowcount == 1

    def mark_processing(self, conn: sqlite3.Connection, *, case_id: str, now: str) -> None:
        conn.execute(
            "UPDATE cases SET processing_started_at = ?, updated_at = ? WHERE id = ?",
            (now, now, case_id))

    def mark_completed(self, conn: sqlite3.Connection, *, case_id: str, now: str) -> None:
        conn.execute(
            "UPDATE cases SET completed_at = ?, updated_at = ? WHERE id = ?",
            (now, now, case_id))


class ArtifactRepository:
    def create(self, conn: sqlite3.Connection, *, artifact_id: str, case_id: str,
               sha256: str, kind: str, media_type: str, extension: str,
               size_bytes: int, storage_key: str, now: str) -> None:
        conn.execute(
            "INSERT INTO artifacts (id, case_id, sha256, kind, media_type, extension,"
            " size_bytes, storage_key, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (artifact_id, case_id, sha256, kind, media_type, extension,
             size_bytes, storage_key, now))

    def list_for_case(self, conn: sqlite3.Connection, case_id: str) -> list[dict]:
        rows = conn.execute(
            "SELECT * FROM artifacts WHERE case_id = ? ORDER BY created_at",
            (case_id,)).fetchall()
        return [dict(row) for row in rows]

    def find_by_sha(self, conn: sqlite3.Connection, sha256: str) -> dict | None:
        return _row_to_dict(
            conn.execute("SELECT * FROM artifacts WHERE sha256 = ? ORDER BY created_at"
                         " LIMIT 1", (sha256,)).fetchone())

    def count_for_case(self, conn: sqlite3.Connection, case_id: str) -> int:
        row = conn.execute("SELECT COUNT(*) FROM artifacts WHERE case_id = ?",
                           (case_id,)).fetchone()
        return int(row[0])

    def get(self, conn: sqlite3.Connection, artifact_id: str) -> dict | None:
        return _row_to_dict(
            conn.execute("SELECT * FROM artifacts WHERE id = ?",
                         (artifact_id,)).fetchone())


class FactRepository:
    def create(self, conn: sqlite3.Connection, *, fact_id: str, case_id: str,
               field: str, value: Any, source: dict, producer: dict,
               taint: str, status: str, validated_by: list[str], now: str) -> None:
        conn.execute(
            "INSERT INTO facts (id, case_id, field, value_json, source_json, producer_json,"
            " taint_class, validation_status, validated_by, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (fact_id, case_id, field, json.dumps(value), json.dumps(source),
             json.dumps(producer), taint, status, json.dumps(validated_by), now))

    def list_for_case(self, conn: sqlite3.Connection, case_id: str) -> list[dict]:
        rows = conn.execute("SELECT * FROM facts WHERE case_id = ? ORDER BY created_at",
                            (case_id,)).fetchall()
        return [dict(row) for row in rows]

    def get(self, conn: sqlite3.Connection, fact_id: str) -> dict | None:
        return _row_to_dict(
            conn.execute("SELECT * FROM facts WHERE id = ?", (fact_id,)).fetchone())

    def update_value(self, conn: sqlite3.Connection, *, fact_id: str, value: Any,
                     status: str, validated_by: list[str]) -> None:
        conn.execute(
            "UPDATE facts SET value_json = ?, validation_status = ?, validated_by = ?"
            " WHERE id = ?",
            (json.dumps(value), status, json.dumps(validated_by), fact_id))

    def update_taint(self, conn: sqlite3.Connection, *, fact_id: str, taint: str,
                     validated_by: list[str]) -> None:
        conn.execute(
            "UPDATE facts SET taint_class = ?, validated_by = ? WHERE id = ?",
            (taint, json.dumps(validated_by), fact_id))

    def delete_for_case(self, conn: sqlite3.Connection, case_id: str) -> None:
        conn.execute("DELETE FROM facts WHERE case_id = ?", (case_id,))


class VendorRepository:
    def create(self, conn: sqlite3.Connection, *, vendor_id: str, name: str,
               name_norm: str, bank_fp: str, catalogue_json: str,
               cap: str | None, now: str) -> None:
        conn.execute(
            "INSERT INTO vendors (vendor_id, name, name_norm, active_bank_fingerprint,"
            " catalogue_json, per_invoice_cap, status, version, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, 'active', 1, ?, ?)",
            (vendor_id, name, name_norm, bank_fp, catalogue_json, cap, now, now))

    def get(self, conn: sqlite3.Connection, vendor_id: str) -> dict | None:
        return _row_to_dict(
            conn.execute("SELECT * FROM vendors WHERE vendor_id = ?", (vendor_id,)).fetchone())

    def get_by_norm(self, conn: sqlite3.Connection, name_norm: str) -> dict | None:
        return _row_to_dict(
            conn.execute("SELECT * FROM vendors WHERE name_norm = ?", (name_norm,)).fetchone())

    def list(self, conn: sqlite3.Connection, *, limit: int, offset: int) -> list[dict]:
        rows = conn.execute(
            "SELECT * FROM vendors ORDER BY name LIMIT ? OFFSET ?", (limit, offset)).fetchall()
        return [dict(row) for row in rows]

    def candidates_by_prefix(self, conn: sqlite3.Connection, prefix: str) -> list[dict]:
        rows = conn.execute(
            "SELECT * FROM vendors WHERE name_norm LIKE ? ESCAPE '\\' AND status = 'active'"
            " ORDER BY name",
            (prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%",)).fetchall()
        return [dict(row) for row in rows]

    def all_active(self, conn: sqlite3.Connection) -> list[dict]:
        rows = conn.execute("SELECT * FROM vendors WHERE status = 'active' ORDER BY name").fetchall()
        return [dict(row) for row in rows]

    def update(self, conn: sqlite3.Connection, *, vendor_id: str, expected_version: int,
               now: str, **fields: Any) -> bool:
        allowed = {"name", "name_norm", "active_bank_fingerprint", "catalogue_json",
                   "per_invoice_cap", "status"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return True
        updates["updated_at"] = now
        sets = ", ".join(f"{key} = ?" for key in updates)
        params: list[Any] = list(updates.values()) + [vendor_id, expected_version]
        cursor = conn.execute(
            f"UPDATE vendors SET {sets}, version = version + 1"  # noqa: S608 - keys allowlisted
            " WHERE vendor_id = ? AND version = ?", params)
        return cursor.rowcount == 1

    def add_bank_change(self, conn: sqlite3.Connection, *, change_id: str, vendor_id: str,
                        new_fp: str, initiated_by: str, requested_at: str,
                        effective_at: str) -> None:
        conn.execute(
            "INSERT INTO vendor_bank_changes (id, vendor_id, new_fingerprint, initiated_by,"
            " requested_at, effective_at, status) VALUES (?, ?, ?, ?, ?, ?, 'pending')",
            (change_id, vendor_id, new_fp, initiated_by, requested_at, effective_at))

    def list_bank_changes(self, conn: sqlite3.Connection, vendor_id: str) -> list[dict]:
        rows = conn.execute(
            "SELECT * FROM vendor_bank_changes WHERE vendor_id = ? ORDER BY requested_at DESC",
            (vendor_id,)).fetchall()
        return [dict(row) for row in rows]

    def due_vendor_ids(self, conn: sqlite3.Connection, now: str) -> list[str]:
        rows = conn.execute(
            "SELECT DISTINCT vendor_id FROM vendor_bank_changes"
            " WHERE status = 'pending' AND effective_at <= ?", (now,)).fetchall()
        return [str(row[0]) for row in rows]

    def activate_due_changes(self, conn: sqlite3.Connection, *, vendor_id: str,
                             now: str) -> list[dict]:
        rows = conn.execute(
            "SELECT * FROM vendor_bank_changes WHERE vendor_id = ? AND status = 'pending'"
            " AND effective_at <= ? ORDER BY requested_at",
            (vendor_id, now)).fetchall()
        due = [dict(row) for row in rows]
        for row in due:
            conn.execute("UPDATE vendor_bank_changes SET status = 'active' WHERE id = ?",
                         (row["id"],))
        return due


class PurchaseOrderRepository:
    def create(self, conn: sqlite3.Connection, *, po_id: str, vendor_id: str,
               po_reference: str, currency: str, original: str, remaining: str) -> None:
        conn.execute(
            "INSERT INTO purchase_orders (po_id, vendor_id, po_reference, currency,"
            " original_amount, remaining_amount, status, version)"
            " VALUES (?, ?, ?, ?, ?, ?, 'open', 1)",
            (po_id, vendor_id, po_reference, currency, original, remaining))

    def get(self, conn: sqlite3.Connection, po_id: str) -> dict | None:
        return _row_to_dict(
            conn.execute("SELECT * FROM purchase_orders WHERE po_id = ?", (po_id,)).fetchone())

    def get_by_reference(self, conn: sqlite3.Connection, vendor_id: str,
                         po_reference: str) -> dict | None:
        return _row_to_dict(
            conn.execute("SELECT * FROM purchase_orders WHERE vendor_id = ? AND po_reference = ?",
                         (vendor_id, po_reference)).fetchone())

    def update_remaining(self, conn: sqlite3.Connection, *, po_id: str, remaining: str,
                         expected_version: int) -> bool:
        cursor = conn.execute(
            "UPDATE purchase_orders SET remaining_amount = ?, version = version + 1"
            " WHERE po_id = ? AND version = ?",
            (remaining, po_id, expected_version))
        return cursor.rowcount == 1


class InvoiceIndexRepository:
    def insert(self, conn: sqlite3.Connection, *, dup_key: str, vendor_id: str,
               case_id: str, number_norm: str, total: str, issue_date: str,
               status: str, now: str) -> None:
        conn.execute(
            "INSERT INTO invoice_index (dup_key, vendor_id, case_id, invoice_number_norm,"
            " total, issue_date, status, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (dup_key, vendor_id, case_id, number_norm, total, issue_date, status, now))

    def get(self, conn: sqlite3.Connection, dup_key: str) -> dict | None:
        return _row_to_dict(
            conn.execute("SELECT * FROM invoice_index WHERE dup_key = ?", (dup_key,)).fetchone())

    def mark_paid(self, conn: sqlite3.Connection, dup_key: str) -> None:
        conn.execute("UPDATE invoice_index SET status = 'paid' WHERE dup_key = ?",
                     (dup_key,))

    def delete_proposed_for_case(self, conn: sqlite3.Connection, case_id: str) -> None:
        conn.execute("DELETE FROM invoice_index WHERE case_id = ? AND status = 'proposed'",
                     (case_id,))


class VerdictRepository:
    def create(self, conn: sqlite3.Connection, *, verdict_id: str, case_id: str,
               verdict: str, reasons: list[str], rule_ids: list[str],
               rule_details: list[dict], policy_version: str, now: str) -> None:
        conn.execute(
            "INSERT INTO verdicts (verdict_id, case_id, verdict, reasons_json, rule_ids_json,"
            " rule_details_json, policy_version, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (verdict_id, case_id, verdict, json.dumps(reasons), json.dumps(rule_ids),
             json.dumps(rule_details), policy_version, now))

    def latest_for_case(self, conn: sqlite3.Connection, case_id: str) -> dict | None:
        return _row_to_dict(
            conn.execute("SELECT * FROM verdicts WHERE case_id = ? ORDER BY created_at DESC"
                         " LIMIT 1", (case_id,)).fetchone())

    def list_for_case(self, conn: sqlite3.Connection, case_id: str) -> list[dict]:
        rows = conn.execute("SELECT * FROM verdicts WHERE case_id = ? ORDER BY created_at",
                            (case_id,)).fetchall()
        return [dict(row) for row in rows]


class ProposalRepository:
    def create(self, conn: sqlite3.Connection, *, proposal_id: str, case_id: str,
               vendor_id: str, payee: str, amount: str, currency: str, due_date: str,
               invoice_ref: str, verdict_id: str, proposal_hash: str,
               policy_version: str, expires_at: str, now: str) -> None:
        conn.execute(
            "INSERT INTO proposals (proposal_id, case_id, vendor_id, payee_display_name,"
            " amount, currency, due_date, invoice_reference, verdict_id, proposal_hash,"
            " policy_version, expires_at, status, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?)",
            (proposal_id, case_id, vendor_id, payee, amount, currency, due_date,
             invoice_ref, verdict_id, proposal_hash, policy_version,
             expires_at, now))

    def get(self, conn: sqlite3.Connection, proposal_id: str) -> dict | None:
        return _row_to_dict(
            conn.execute("SELECT * FROM proposals WHERE proposal_id = ?", (proposal_id,)).fetchone())

    def get_by_case(self, conn: sqlite3.Connection, case_id: str) -> dict | None:
        return _row_to_dict(
            conn.execute("SELECT * FROM proposals WHERE case_id = ? ORDER BY created_at DESC"
                         " LIMIT 1", (case_id,)).fetchone())

    def set_status(self, conn: sqlite3.Connection, proposal_id: str, status: str) -> None:
        conn.execute("UPDATE proposals SET status = ? WHERE proposal_id = ?",
                     (status, proposal_id))

    def list_pending_for_case(self, conn: sqlite3.Connection, case_id: str) -> list[dict]:
        rows = conn.execute("SELECT * FROM proposals WHERE case_id = ? AND status = 'PENDING'"
                            " ORDER BY created_at", (case_id,)).fetchall()
        return [dict(row) for row in rows]

    def list(self, conn: sqlite3.Connection, *, limit: int, offset: int) -> list[dict]:
        rows = conn.execute(
            "SELECT * FROM proposals ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset)).fetchall()
        return [dict(row) for row in rows]

    def count_by_status(self, conn: sqlite3.Connection) -> dict[str, int]:
        rows = conn.execute(
            "SELECT status, COUNT(*) FROM proposals GROUP BY status").fetchall()
        return {str(status): int(count) for status, count in rows}


class SessionRepository:
    def create(self, conn: sqlite3.Connection, *, session_id: str, token_hash: str,
               csrf_hash: str, now: str, expires_at: str) -> None:
        conn.execute(
            "INSERT INTO auth_sessions (session_id, token_hash, csrf_hash, owner_id,"
            " created_at, expires_at, last_activity_at, revoked_at)"
            " VALUES (?, ?, ?, 'owner', ?, ?, ?, NULL)",
            (session_id, token_hash, csrf_hash, now, expires_at, now))

    def get_by_token_hash(self, conn: sqlite3.Connection, token_hash: str) -> dict | None:
        return _row_to_dict(
            conn.execute("SELECT * FROM auth_sessions WHERE token_hash = ?", (token_hash,)).fetchone())

    def get(self, conn: sqlite3.Connection, session_id: str) -> dict | None:
        return _row_to_dict(
            conn.execute("SELECT * FROM auth_sessions WHERE session_id = ?", (session_id,)).fetchone())

    def touch(self, conn: sqlite3.Connection, session_id: str, now: str) -> None:
        conn.execute("UPDATE auth_sessions SET last_activity_at = ? WHERE session_id = ?",
                     (now, session_id))

    def revoke(self, conn: sqlite3.Connection, session_id: str, now: str) -> None:
        conn.execute("UPDATE auth_sessions SET revoked_at = ? WHERE session_id = ?",
                     (now, session_id))

    def set_csrf_hash(self, conn: sqlite3.Connection, session_id: str,
                      csrf_hash: str) -> None:
        conn.execute("UPDATE auth_sessions SET csrf_hash = ? WHERE session_id = ?",
                     (csrf_hash, session_id))


class ChallengeRepository:
    """Challenge persistence. All methods take the SHA-256 `challenge_hash`
    (migration 003); raw bearers never reach this layer."""

    def create(self, conn: sqlite3.Connection, *, challenge_hash: str, proposal_hash: str,
               session_id: str, now: str, expires_at: str) -> None:
        conn.execute(
            "INSERT INTO auth_challenges (challenge_hash, proposal_hash, session_id,"
            " created_at, expires_at, used_at, failed_attempts)"
            " VALUES (?, ?, ?, ?, ?, NULL, 0)",
            (challenge_hash, proposal_hash, session_id, now, expires_at))

    def get(self, conn: sqlite3.Connection, challenge_hash: str) -> dict | None:
        return _row_to_dict(
            conn.execute("SELECT * FROM auth_challenges WHERE challenge_hash = ?",
                         (challenge_hash,)).fetchone())

    def mark_used(self, conn: sqlite3.Connection, challenge_hash: str, now: str) -> bool:
        cursor = conn.execute(
            "UPDATE auth_challenges SET used_at = ? WHERE challenge_hash = ? AND used_at IS NULL",
            (now, challenge_hash))
        return cursor.rowcount == 1

    def increment_failures(self, conn: sqlite3.Connection, challenge_hash: str) -> None:
        conn.execute("UPDATE auth_challenges SET failed_attempts = failed_attempts + 1"
                     " WHERE challenge_hash = ?", (challenge_hash,))


class PaymentRepository:
    def create(self, conn: sqlite3.Connection, *, payment_id: str, proposal_id: str,
               idempotency_key: str, proposal_hash: str, case_id: str,
               amount: str, currency: str, now: str) -> None:
        conn.execute(
            "INSERT INTO mock_payments (payment_id, proposal_id, idempotency_key,"
            " proposal_hash, case_id, amount, currency, executed_at, status)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'MOCK_COMPLETED')",
            (payment_id, proposal_id, idempotency_key, proposal_hash, case_id,
             amount, currency, now))

    def get(self, conn: sqlite3.Connection, payment_id: str) -> dict | None:
        return _row_to_dict(
            conn.execute("SELECT * FROM mock_payments WHERE payment_id = ?", (payment_id,)).fetchone())

    def get_by_idempotency(self, conn: sqlite3.Connection, key: str) -> dict | None:
        return _row_to_dict(
            conn.execute("SELECT * FROM mock_payments WHERE idempotency_key = ?", (key,)).fetchone())

    def get_by_proposal(self, conn: sqlite3.Connection, proposal_id: str) -> dict | None:
        return _row_to_dict(
            conn.execute("SELECT * FROM mock_payments WHERE proposal_id = ?"
                         " ORDER BY executed_at DESC LIMIT 1", (proposal_id,)).fetchone())

    def list_for_case(self, conn: sqlite3.Connection, case_id: str) -> list[dict]:
        rows = conn.execute("SELECT * FROM mock_payments WHERE case_id = ? ORDER BY executed_at",
                            (case_id,)).fetchall()
        return [dict(row) for row in rows]

    def count_all(self, conn: sqlite3.Connection) -> int:
        row = conn.execute("SELECT COUNT(*) FROM mock_payments").fetchone()
        return int(row[0])


class AuditRepository:
    def latest(self, conn: sqlite3.Connection) -> dict | None:
        return _row_to_dict(
            conn.execute("SELECT * FROM audit_events ORDER BY id DESC LIMIT 1").fetchone())

    def insert(self, conn: sqlite3.Connection, *, ts: str, case_id: str | None,
               event_type: str, actor_type: str, actor_id: str | None,
               payload: dict, prev_hash: str, event_hash: str) -> int:
        cursor = conn.execute(
            "INSERT INTO audit_events (ts, case_id, event_type, actor_type, actor_id,"
            " payload_json, prev_hash, event_hash)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (ts, case_id, event_type, actor_type, actor_id,
             json.dumps(payload), prev_hash, event_hash))
        return int(cursor.lastrowid or 0)

    def list_for_case(self, conn: sqlite3.Connection, case_id: str,
                      *, limit: int = 500) -> list[dict]:
        rows = conn.execute(
            "SELECT * FROM audit_events WHERE case_id = ? ORDER BY id LIMIT ?",
            (case_id, limit)).fetchall()
        return [dict(row) for row in rows]

    def recent(self, conn: sqlite3.Connection, *, limit: int,
               offset: int) -> list[dict]:
        rows = conn.execute(
            "SELECT * FROM audit_events ORDER BY id DESC LIMIT ? OFFSET ?",
            (limit, offset)).fetchall()
        return [dict(row) for row in rows]

    def all_ordered(self, conn: sqlite3.Connection) -> list[dict]:
        rows = conn.execute("SELECT * FROM audit_events ORDER BY id").fetchall()
        return [dict(row) for row in rows]


class RateLimitRepository:
    def get(self, conn: sqlite3.Connection, scope_key: str) -> dict | None:
        return _row_to_dict(
            conn.execute("SELECT * FROM rate_limits WHERE scope_key = ?", (scope_key,)).fetchone())

    def upsert(self, conn: sqlite3.Connection, *, scope_key: str, window_start: str,
               count: int) -> None:
        conn.execute(
            "INSERT INTO rate_limits (scope_key, window_start, count) VALUES (?, ?, ?)"
            " ON CONFLICT(scope_key) DO UPDATE SET window_start = excluded.window_start,"
            " count = excluded.count",
            (scope_key, window_start, count))

    def reset(self, conn: sqlite3.Connection, scope_key: str) -> None:
        conn.execute("DELETE FROM rate_limits WHERE scope_key = ?", (scope_key,))


class EvalRepository:
    def create(self, conn: sqlite3.Connection, *, run_id: str, now: str) -> None:
        conn.execute(
            "INSERT INTO eval_runs (run_id, created_at, status, summary_json, results_json)"
            " VALUES (?, ?, 'running', '{}', '[]')", (run_id, now))

    def finish(self, conn: sqlite3.Connection, *, run_id: str, status: str,
               summary: dict, results: list[dict]) -> None:
        conn.execute(
            "UPDATE eval_runs SET status = ?, summary_json = ?, results_json = ?"
            " WHERE run_id = ?",
            (status, json.dumps(summary), json.dumps(results), run_id))

    def get(self, conn: sqlite3.Connection, run_id: str) -> dict | None:
        return _row_to_dict(
            conn.execute("SELECT * FROM eval_runs WHERE run_id = ?", (run_id,)).fetchone())
