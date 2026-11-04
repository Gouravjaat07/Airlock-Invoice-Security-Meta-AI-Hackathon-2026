# Airlock Product Impact

## Target users

Small finance teams and owner-operated businesses that pay supplier
invoices and cannot staff a full accounts-payable control function: the
owner (or a single bookkeeper) who today eyeballs PDFs and pays from
their bank app.

## Core problem

Supplier-invoice fraud and error take a few concrete shapes: bank-detail
substitution on an otherwise valid invoice, duplicate billing for the
same work, invoices that do not match any purchase order, arithmetic
that does not reconcile, and lookalike vendors. A busy owner checking
email attachments by hand catches these inconsistently, and every miss
is either money lost or hours spent unwinding a payment.

## Existing workflow and pain points

Today: invoice arrives as a PDF → owner skims it → checks (maybe) that
the vendor looks right → pays. Vendor bank records live nowhere
authoritative; PO matching is manual; duplicates are caught by memory;
delivery evidence (photos, voice notes from the warehouse) never meets
the invoice in one place. AI summarizers make this faster but add a new
failure: the model can be instructed by the document it reads.

## Airlock workflow

Upload invoice + optional delivery photo/video + optional voice note →
typed AI extraction (untrusted) → deterministic checks against
owner-seeded vendor/bank/PO records → multimodal corroboration →
R1–R10 policy verdict → proposal the owner confirms with session +
challenge + PIN → mock execution record with a tamper-evident audit
trail. The owner still authorizes every payment; the system does the
checking they would skip under time pressure.

## Distinctive innovation

Airlock is not invoice OCR. It is an evidence-grounded payment-control
pipeline that separates untrusted multimodal interpretation from
deterministic financial policy and owner authorization:

1. Typed extraction with page-level provenance, never trusted values.
2. Trusted vendor/bank resolution with fingerprint comparison.
3. PO reconciliation (status, currency, remaining balance).
4. Exact Decimal arithmetic and canonical duplicate identity.
5. Multimodal corroboration (voice transcript comparison, SAM
   geometry counts) as optional, explicitly-labeled evidence.
6. Prompt-injection resistance by architecture (extract-only prompts,
   T2 taint, policy ignores prose).
7. Deterministic R1–R10 verdicts with reason codes.
8. Evidence-level provenance for every stored fact.
9. Owner-only confirmation with stale-verdict and race guards.
10. Mock-only execution, so the prototype cannot move money.

## Measurable benefits (pilot-assumable, not yet measured)

No customer data exists; do not cite any. A pilot could measure:
duplicate-invoice catch rate on seeded history, bank-mismatch catch
rate, minutes from upload to decision, and false-escalation rate. The
offline benchmark (19 synthetic scenarios, 19 matched, 0 false-ALLOW)
is a regression signal, not a field-accuracy claim — see
[evaluation/MODEL_BENCHMARK_REPORT.md](evaluation/MODEL_BENCHMARK_REPORT.md).

## Limitations

Single-owner prototype; SQLite single node; fixture/mock providers
unless the owner configures live keys; live model quality unevaluated;
English-centric prompts; no ERP/bank integration (mock execution by
design); 19-scenario benchmark is preliminary.

## Future commercialization roadmap

1. Pilot with synthetic + owner-provided history (read-only, no keys).
2. Live-provider quality eval (opt-in, capped spend) before any claim.
3. Multi-user roles (preparer/approver) with the same T0 guarantees.
4. PostgreSQL migration at the repository boundary already documented.
5. ERP export (proposals as data, execution stays outside Airlock).

## Pilot deployment assumptions

One trusted operator; owner-seeded vendor/bank/PO records; fixture or
owner-keyed providers; isolated host or VPC; daily audit-verify;
no real banking credentials in scope.
