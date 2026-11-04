# Airlock Data Flow

Companion: [ARCHITECTURE.md](ARCHITECTURE.md),
[phase1 privacy](phase1/DATA_FLOW_AND_PRIVACY.md),
[policy engine](POLICY_ENGINE.md).

## Intake (untrusted → recorded)

1. Multipart upload (≤5 files, ≤10 MiB each, 64 MiB form cap):
   invoice PDF/PNG/JPEG required; delivery PNG/JPEG/MP4 and voice WAV
   optional.
2. Extension allowlist + magic-byte sniff + kind cross-check; corrupt
   PNG/truncated PDF/encrypted PDF/empty rejected (`storage/artifacts.py`).
3. SHA-256 hashed; idempotency key + content dedup; atomic DB row +
   blob write with rollback (`pipeline/ingest.py`).

## Interpretation (untrusted → T2 facts)

4. Registry-selected reader transcribes the invoice to strict
   `InvoiceExtraction` (extra=forbid, Decimal, currency v5).
   Malformed output → R8 DENY, never a crash.
5. SAM lane: delivery bytes + trusted-catalogue concept → count/boxes
   (geometry only). Voice lane: WAV → transcript → deterministic
   token/amount comparison. Each lane yields a typed `LaneOutcome`
   (MISSING/EVALUATED/NOT_EVALUATED/FAILED/EMPTY).
6. Facts stored with source (artifact/page) + producer
   (adapter/model/prompt/request) + T2 taint + validator list.

## Decision (trusted records + T2 facts → verdict)

7. Corroboration compares facts against the owner-seeded
   vendor/bank/PO registries and duplicate index, recording only
   validators that actually ran.
8. Policy R1–R10 evaluates every rule; precedence R9 > DENY >
   ESCALATE > ALLOW_PROPOSAL. Verdict + rule details persisted;
   ALLOW creates a canonical-hash proposal; ESCALATE/DENY set
   NEEDS_REVIEW/REJECTED.

## Authorization (T0 owner only)

9. Owner opens proposal → session-bound one-time challenge (5 min) →
   confirms with PIN → server re-verifies challenge, PIN, proposal
   hash, expiry, current ALLOW verdict → mock execution recorded.
10. Every step appends to the hash-chained audit log in the same
    transaction as the business write.

## What never flows

Model outputs never reach registries, policy inputs unvalidated,
proposal hashes, challenges, payments, or audit hashes. Secrets never
leave the process except as redacted presence flags; provider calls
carry only the artifact bytes + task prompt over TLS.
