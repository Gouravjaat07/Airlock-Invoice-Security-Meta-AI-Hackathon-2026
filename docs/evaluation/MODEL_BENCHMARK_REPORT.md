# Airlock Model Benchmark Report

Date: 2026-11-04. Evaluator: mission session (offline only).
Dataset: canonical synthetic fixtures — 23 binaries + 19 scenarios
(`python scripts/make_fixtures.py --check` → green).
Integrity: deterministic regeneration check, not a hash manifest.
Machine-readable snapshot: [benchmark_snapshot_2026-11-04.json](benchmark_snapshot_2026-11-04.json)
(regenerable; see commands below).

## 1. What was measured (and what was not)

| Layer | Result | Meaning |
|---|---|---|
| Offline deterministic pipeline | 19/19 verdicts matched, false-ALLOW 0/10 | Regression signal on synthetic ground truth. NOT model quality: no provider was called. |
| Offline fixture schema | 15/15 payloads schema-valid | Schema-drift signal. |
| Mocked adapter contracts | 941-test suite green (2 env-blocked, 1 skipped) | Contract + pipeline behavior, not live quality. |
| Live Spark extraction quality | NOT_TESTED | Zero billable calls in this mission. Metric: `score_extraction` per-field accuracy. |
| Live voice quality (WER/CER) | NOT_TESTED | Metric defined + unit-tested (`app/evaluation/media_metrics.py`); no labelled audio run. |
| Live SAM quality (count MAE) | NOT_TESTED | Metric defined + unit-tested; no labelled masks; geometry-only by design. |

These layers are never combined into one accuracy number.

## 2. Offline policy evaluation (authoritative for pipeline behavior)

Command: `.\.venv\Scripts\python.exe scripts\phase3_eval.py --output-dir results\phase3\eval`
Output: `results/phase3/eval/phase3_eval.json` (gitignored; snapshot in §6).
Tool version 0.1.0, policy v2.0.0, elapsed 1165 ms, 2026-11-04T17:03Z.

- Total 19, matched 19, accuracy 1.0 — on this synthetic regression set only.
- Per-verdict: ALLOW_PROPOSAL P=1.0 R=1.0 (n=5); ESCALATE P=1.0 R=1.0
  (n=6); DENY P=1.0 R=0.875 (n=8).
- The DENY recall 0.875 is honest, not a bug: `reader-timeout` declares
  `reader_error` in its spec, so the fail-closed `ERROR:E_READER_TIMEOUT`
  (no verdict, no proposal) counts as a match while not being an
  exact-DENY. DENY support 8 = 7 exact + 1 declared-error.
- Confusion (actual → expected): ALLOW 5/0/0; ESCALATE 0/6/0; DENY
  0/0/7; ERROR 0/0/1.
- Rule triggers: R1×2 R2×3 R3×2 R4×3 R5×3 R6×2 R7×2 R8×2 R9×1 R10×2 —
  every rule fires at least once.
- Adversarial scenarios: 10 (attack_type A01–A16 vocabulary);
  false-ALLOW: 0. Attack samples whose ground truth is ALLOW_PROPOSAL
  (injection-inertness proofs) correctly do not count as false-ALLOW.

Per-scenario: ambiguous-vendor E→E; arithmetic-mismatch D→D;
changed-bank D→D; clean A→A; duplicate D→D; hidden-text A→A;
injection-visible A→A; invalid-due E→E; lookalike-vendor D→D;
malformed-reader D→D; missing-field D→D; over-cap E→E;
planner-injection A→A; po-exceeded E→E; reader-timeout D→ERROR
(declared); sam-conflict E→E; sam-ok A→A; verifier-timeout D→D;
voice-instruction E→E.

## 3. Offline schema + eval-gate summary

Command: `.\.venv\Scripts\python.exe scripts\phase5_eval.py`
Result: `verdict 19/19 matched, false-ALLOW=0, schema 15/15, live=NOT_TESTED`.
The 4 non-schema scenarios are failure variants (invalid payloads are
legitimate test inputs, covered by the verdict part).

## 4. Extraction metric definition (live scoring, ready but not run)

`scripts/phase5_eval.py::score_extraction`: casefold text match on
vendor_name/invoice_number/currency/bank_reference/po_reference; exact
ISO dates; strict Decimal money; line-item count + exact per-line
(description casefold, exact qty/price). Reports per-field hits,
accuracy, complete_match, plus request_id/model_id/latency/warnings.
Live command (explicit, billable, owner-only):

```powershell
python scripts\phase5_eval.py --live --allow-billable --reader-provider spark --max-calls 3
```

## 5. Voice and vision metric definitions (ready but not run)

`app/evaluation/media_metrics.py` (unit-tested, `tests/unit/test_media_metrics.py`):
WER/CER with casefolded Levenshtein matching; undefined (None, never 0)
for empty-reference/non-empty-hypothesis; signed count error; MAE;
deterministic discrepancy rule mirroring corroboration tolerance.

Available ground truth today: 1 scenario transcript
(`voice-instruction`, adversarial instruction text), 2 SAM count specs
(`sam-ok`=30, `sam-conflict`=5). Too small for model-quality claims;
suitable only as fixture-consistency checks. No WER/IoU/Dice numbers
are reported because no live run exists. Do not claim object
classification: the SAM adapter returns geometry + counts only.

## 6. Snapshot + limitations

Snapshot: [benchmark_snapshot_2026-11-04.json](benchmark_snapshot_2026-11-04.json)
(phase3 summary + per-scenario outcomes + environment).

Limitations (preliminary — small-n, no confidence intervals):
single 19-scenario regression set; no train/dev split; vendors shared
across scenarios (e.g. Acme Flour Co) so no vendor-grouped split is
possible; `clean`/`duplicate` share an invoice identity by design (R4
test); near-duplicate documents across partitions not applicable (no
partitions). A zero false-ALLOW on 10 adversarial scenarios is evidence
about this benchmark, not a universal security guarantee. No
calibration analysis: no component emits a validated probability.
