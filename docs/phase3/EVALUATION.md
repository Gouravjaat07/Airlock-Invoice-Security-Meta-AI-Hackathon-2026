# Phase 3 — Evaluation guide

## What is measured (offline, deterministic)

`python scripts/phase3_eval.py` runs the real pipeline over all
`fixtures/scenarios/*.json` (isolated temp DB, seeded synthetic
registry, fixture reader) and writes
`results/phase3/eval/phase3_eval.{json,md}`:

- Verdict accuracy (expected vs actual per scenario).
- Per-verdict precision/recall/support.
- Actual-vs-expected confusion counts.
- R1–R10 trigger frequencies.
- Adversarial false-ALLOW count (**must be 0**; exit 1 otherwise).
- Elapsed time.

Scenario ground truth is the checked-in `expected_verdict` +
`attack_type` (canonical manifest v2 field, preserved). No
thresholds were tuned; R1–R10 are untouched.

Two counting rules (3.2 remediation, with rationale):

- **False-ALLOW** counts an attack-typed scenario only when its
  ground truth requires non-allowance (`DENY`/`ESCALATE`) yet the
  pipeline returned `ALLOW_PROPOSAL`. Attack scenarios whose ground
  truth is `ALLOW_PROPOSAL` (hidden-text, injection-visible,
  planner-injection) prove injection-inertness — valid values
  decide, hostile text stays quoted T2 data — and must not count.
  Counting them would demand rejecting financially valid invoices
  for containing suspicious words.
- **Declared failure injections**: a scenario carrying
  `reader_error` documents the fail-closed ERROR path ("no
  verdict"). It matches when the pipeline raises exactly the
  declared error code with no proposal. The error result always
  records the documented expectation (never null). Transient reader
  failures stay retryable ERRORs; they are deliberately NOT
  converted into DENY verdicts.

## What is NOT claimed

This evaluates deterministic pipeline behavior, not model quality:
the fixture reader replays scenario extractions, so field-level
extraction accuracy against these scenarios would be tautological
and is not reported. Provider-output validation is instead covered
by contract tests (`tests/providers/`) with stubbed responses, and
adversarial robustness by injection suites that route hostile model
outputs through the real pipeline (must DENY/ERROR, never ALLOW).

Live model-quality eval (extraction F1, WER, segmentation mAP on
non-synthetic data) requires credentials + a labelled corpus and is
BLOCKED. No confidence calibration is claimed; model uncertainty
metadata is advisory only.

## Commands

```powershell
.\.venv\Scripts\python.exe scripts/phase3_eval.py
.\.venv\Scripts\python.exe scripts/phase3_eval.py --output-dir results/phase3/eval
```

Results from the acceptance run are recorded in the final report
(§H), not hand-copied here.
