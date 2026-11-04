# Phase 4 — Offline Fixture Workflow (Browser E2E)

How to process synthetic invoices through the real React UI with the
fixture reader, and how to register a new synthetic fixture for
dev/test. No live model calls, no real payments.

## 1. Root cause of `Artifact is not a registered synthetic fixture`

The fixture reader (`app/adapters/readers.py`) identifies fixtures
**only by SHA-256 of the artifact bytes**: it hashes the uploaded
invoice and looks the digest up in the scenario index built from
`fixtures/scenarios/*.json` (`invoice_artifact` files). There is no
name/reference-based registration; the UI artifact ids (`art_...`)
are opaque and irrelevant to the reader.

The failing flow was, step by step:

1. Browser upload `POST /api/v1/cases` — intake validated the novel
   synthetic PDF, stored the blob, recorded its SHA-256. Case created.
2. `Process case` → `POST /api/v1/cases/{id}/process` → pipeline
   loaded the bytes, verified them against the recorded hash, and
   called `FixtureReader.read(bytes)`.
3. The bytes' SHA-256 matched no scenario → `E_READER_UNAVAILABLE`
   (`Artifact is not a registered synthetic fixture`).
4. The case moved to `ERROR` (audited `reader.started` /
   `reader.error` events); the API returned HTTP 503 with an error
   envelope carrying `request_id: req_...`.
5. The frontend renders `{message} ref {requestId}` — the `ref ...`
   suffix is the request id, not part of the error.

The 503 mapping is intended (`STATUS_BY_CODE` in
`app/core/errors.py`). The rejection is correct behavior: a novel
upload must never be trusted as a fixture on the basis of its
filename, form fields, PDF text, or model output. What was missing
was a **supported way to register new synthetic content**, which this
phase adds (dev/test only, content-hash bound).

## 2. Workflow A — process a registered fixture via the UI (no setup)

Upload the exact bytes of an already-registered fixture. This is the
same path the Playwright smoke test uses
(`fixtures/invoices/clean.pdf` → `ALLOW_PROPOSAL`).

1. Start the backend (fixture reader enabled, dev only):
   ```powershell
   cd D:\Downloads\Meta_Hackathon_2026
   $env:AIRLOCK_ENV='development'
   $env:AIRLOCK_FIXTURE_READER='1'
   $env:AIRLOCK_READER_PROVIDER='fixture'
   $env:AIRLOCK_VOICE_PROVIDER='mock'
   $env:AIRLOCK_VISION_PROVIDER='mock'
   .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
   ```
2. Start the frontend in a second terminal:
   ```powershell
   cd D:\Downloads\Meta_Hackathon_2026\web
   npm run dev -- --host 127.0.0.1
   ```
3. Open `http://127.0.0.1:5173`, sign in with the owner PIN.
4. New case → attach `D:\Downloads\Meta_Hackathon_2026\fixtures\invoices\clean.pdf`
   → Submit → open the case → **Process case**.
5. Expect: extracted facts with `fixture-reader` provenance, R1–R10
   all passing, verdict `ALLOW_PROPOSAL`, proposal `PENDING`, audit
   events, and no payment until the owner approval flow runs.

To confirm a file resolves before uploading:

```powershell
cd D:\Downloads\Meta_Hackathon_2026
$env:AIRLOCK_ENV='development'
$env:AIRLOCK_FIXTURE_READER='1'
.\.venv\Scripts\python.exe -m app.cli fixtures verify --file .\fixtures\invoices\clean.pdf
.\.venv\Scripts\python.exe -m app.cli fixtures list
```

## 3. Workflow B — register a new synthetic invoice (dev/test only)

Use this for a novel synthetic PDF (e.g. the Global Digital Ventures
test invoice). Registration is an explicit owner action at the
terminal; it never happens automatically from an upload.

### 3.1 Point the backend at a custom fixtures directory

```powershell
cd D:\Downloads\Meta_Hackathon_2026
$env:AIRLOCK_ENV='development'
$env:AIRLOCK_FIXTURE_READER='1'
$env:AIRLOCK_CUSTOM_FIXTURES_DIR='D:\Downloads\Meta_Hackathon_2026\fixtures-custom'
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

The backend reads this variable at startup: if it was already
running, restart it after setting the variable. Keep the same
variable set in the terminal used for registration below.
Production refuses this variable entirely (`load_settings` fails
closed), and registration refuses `AIRLOCK_ENV=production`.

### 3.2 Author the extraction JSON from the PDF

Transcribe the values **from the PDF itself**. The payload must pass
the strict extraction schema and its arithmetic must reconcile
(`sum(qty*price) == subtotal`, `subtotal + tax == total`), otherwise
the pipeline fails closed at R3/R8. Template for the current test
invoice (verify every value against the PDF; the subtotal/tax split
and the bank reference below are placeholders until confirmed):

```json
{
  "vendor_name": "Global Digital Ventures",
  "invoice_number": "INV-2023-773",
  "issue_date": "2026-11-02",
  "due_date": "2026-12-02",
  "currency": "USD",
  "subtotal": "2700.00",
  "tax": "122.27",
  "total": "2822.27",
  "bank_reference": "TRANSCRIBE-FROM-PDF",
  "po_reference": null,
  "line_items": [
    {"description": "TRANSCRIBE-FROM-PDF", "quantity": "1",
     "unit_price": "2700.00"}
  ]
}
```

Save it as e.g. `D:\temp\global-digital.extraction.json`. The
beneficiary holder/bank names from the PDF have no trusted standing:
whatever `bank_reference` is transcribed is fingerprinted and
compared against the vendor registry by R2; an unknown vendor means
no trust regardless (see §5).

### 3.3 Register, verify, upload

```powershell
cd D:\Downloads\Meta_Hackathon_2026
$env:AIRLOCK_ENV='development'
$env:AIRLOCK_FIXTURE_READER='1'
$env:AIRLOCK_CUSTOM_FIXTURES_DIR='D:\Downloads\Meta_Hackathon_2026\fixtures-custom'
.\.venv\Scripts\python.exe -m app.cli fixtures register `
  --name global-digital-773 `
  --invoice 'D:\path\to\synthetic-invoice.pdf' `
  --extraction 'D:\temp\global-digital.extraction.json' `
  --expected-verdict DENY `
  --notes 'Manual browser test: unknown vendor + beneficiary mismatch'
.\.venv\Scripts\python.exe -m app.cli fixtures verify --file 'D:\path\to\synthetic-invoice.pdf'
```

The register step prints the SHA-256 binding, the scenario path, and
whether the backend session sees the directory. Then upload the
**exact same PDF bytes** through New case → Process case.

Optional delivery/voice evidence for the same scenario:

```powershell
.\.venv\Scripts\python.exe -m app.cli fixtures register `
  --name global-digital-773 --invoice 'D:\path\to\synthetic-invoice.pdf' `
  --extraction 'D:\temp\global-digital.extraction.json' `
  --expected-verdict DENY --force `
  --delivery 'D:\path\to\delivery.png' --sam-count 1 `
  --voice 'D:\path\to\note.wav' --transcript 'Delivery confirmed.'
```

## 4. Retry semantics for the two ERROR cases

The existing `ERROR` cases are preserved with their audit history.
Retry is supported and safe:

- The state machine allows `ERROR → READING`, and the case page
  shows **Retry processing** for `ERROR` cases.
- Retry re-reads the stored bytes and re-runs read → validate →
  corroborate → R1–R10; previous artifacts and audit events stay
  intact (new attempt events are appended).
- No duplicate proposals can result: reprocessing rejects stale
  `PENDING` proposals (`superseded-by-reprocess`), clears the case's
  proposed duplicate key, and completed cases return the existing
  outcome idempotently.

After registering the novel PDF (§3), clicking **Retry processing**
on those cases processes them. Alternatively, upload the bytes as a
new case. Never edit SQLite rows to force a status.

## 5. Expected policy outcome for the test invoice (derived, not fixed)

From `policy/rules.toml` and `registry/synthetic_vendors.json`:

- `Global Digital Ventures` is not in the vendor registry → **R1
  fails → verdict DENY**, no proposal, no payment. R4 is likewise
  unverifiable without a resolved vendor.
- The beneficiary account (`VexaX Solutions Inc` / National Bank) is
  untrusted input: the transcribed `bank_reference` is HMAC
  fingerprinted and compared to the vendor's registered fingerprint
  by R2. With no registered vendor there is nothing to match, so the
  beneficiary can never become trusted payment details.
- The pipeline, not the `--expected-verdict` label, decides. If the
  transcribed arithmetic does not reconcile, R3 additionally fails
  closed. Either way the outcome is DENY with no proposal.

## 6. Security properties (preserved)

- Registration is terminal-explicit, content-hash bound
  (exact-byte SHA-256 match at read time), schema-validated with the
  production validator, and intake-validated with the production
  upload checks.
- Custom fixtures live outside `fixtures/`, cannot shadow canonical
  fixtures by name or by bytes, and never enter the Phase 3 offline
  evaluation (19 canonical scenarios) or `make_fixtures --check`.
- Production disables everything: `load_settings` rejects
  `AIRLOCK_CUSTOM_FIXTURES_DIR`, the fixture reader, and mock
  providers when `AIRLOCK_ENV=production`.
- Registration grants no vendor/bank trust, creates no proposals,
  and cannot approve anything: R1–R10 and the owner
  challenge/PIN/mock-payment flow are unchanged.

## 7. Verification commands

```powershell
cd D:\Downloads\Meta_Hackathon_2026
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pytest tests\integration\test_fixture_registration.py -q
.\.venv\Scripts\python.exe -m ruff check scripts tests app
.\.venv\Scripts\python.exe scripts\phase2_check.py --strict
.\.venv\Scripts\python.exe scripts\phase3_eval.py
.\.venv\Scripts\python.exe scripts\phase3_check.py --strict
.\.venv\Scripts\python.exe scripts\make_fixtures.py --check
cd web
npm test; npm run typecheck; npm run lint; npm run build
# Real-browser E2E (isolated temp DB; see web/e2e/smoke.mjs prereqs):
$env:AIRLOCK_E2E_PIN='<owner pin>'; npm run e2e
```

Live Meta/Baseten/Voice/SAM/Glimmer integrations remain
**UNTESTED** (no live calls are made by any gate above).
