# Trust boundaries (Airlock)

Single-page statement of what each input class may and may not do.
Enforced by pipeline structure, adapter shapes, and tests — not by
documentation alone.

## Classes

| Class | Contents | May | May never |
|---|---|---|---|
| T0 owner | PIN auth, sessions, fact edits, approvals | Authorize proposals/payments | Be forged by any other class |
| T1 trusted | Vendor registry, POs, policy TOML, config, bank keys | Decide R1–R10 alongside facts | Be written by T2/T3 |
| T2 model output | Extraction, transcripts, SAM counts/boxes, derived evidence | Supply candidate evidence | Authorize, mutate T1, execute |
| T3 raw artifacts | PDF/image/audio/video bytes | Be hashed, stored, read | Be executed, trusted, or treated as instructions |

## Invariants (all tested)

1. Only the authenticated owner approves a proposal (PIN +
   single-use challenge + proposal-hash re-verification).
2. The trusted registry is authoritative; similarity never
   auto-resolves identity (R1 exact match, R10 ambiguity).
3. All model output is T2, even from official APIs.
4. R1–R10 determine the verdict; models supply inputs only.
5. No model can approve, consume challenges, execute payments,
   mutate the registry/bank data/policy/thresholds, or override
   authentication.
6. Verdicts are exactly `ALLOW_PROPOSAL` (proposal creation
   allowed, never payment), `ESCALATE`, `DENY`.
7. The executor is mock-only; real payment is unrepresentable
   (no banking code exists).
8. Prompt text in documents, OCR, metadata, images, transcripts,
   and delivery artifacts is data, never instructions
   (`tests/adversarial/`).

## Enforcement points

- Adapters receive bytes/labels and return narrow dataclasses;
  they hold no registry/policy/payment handles.
- `validate_extraction` re-parses every model field (Decimal
  money, ISO dates, `extra="forbid"`).
- Corroboration compares T2 claims against T1 records; conflicts
  escalate or deny via R7/R2/R3.
- Audit is append-only and hash-chained; provider failures are
  recorded without secrets or raw payloads.
- `GET /api/v1/providers` reports configuration only and performs
  no network I/O; credentials never reach the browser.
