# Phase 5 benchmark methodology

How the numbers in `PHASE5_RESULTS.md` are produced. Everything is
reproducible from a clean checkout; nothing is estimated by hand.

## Offline pipeline benchmark

- Tool: `python scripts/phase5_benchmark.py --cases N`
  (default evidence: `results/phase5/benchmark_summary.json` +
  `benchmark_report.md`).
- Setup: isolated temp DB (`database.upgrade`), seeded synthetic
  registry (`registry/synthetic_vendors.json`), temp blob store,
  fixture reader + mock voice/SAM, eval API enabled in `test`
  env. No network, no keys.
- Workload: N end-to-end `run_scenarios` single-case runs over
  rotating canonical scenarios (declared failure-injection
  scenarios excluded — they measure error paths, not latency).
- Reported: per-case latency min/P50/P95/max/mean, verdict
  distribution, audit event count, throughput (cases/s), plus
  python/platform/tool/commit provenance.
- Timings are machine observations, not targets; inputs are
  deterministic, durations are not asserted.

## Evaluation (accuracy + safety)

- Tool: `python scripts/phase5_eval.py` → `results/phase5/eval/`.
- Verdict part: runs `scripts/phase3_eval.py` (authoritative
  subprocess) over every canonical scenario — match rate,
  per-verdict precision/recall, rule triggers, adversarial
  false-ALLOW (must be 0; nonzero fails the run).
- Schema part: every canonical `extraction` payload re-validated
  against the live `InvoiceExtraction` + arithmetic checks
  (schema-drift signal, not model accuracy).
- Live reader part (opt-in `--live --allow-billable
  --reader-provider spark|spark-open|glimmer --max-calls N≤10`):
  the real adapter calls the real provider over synthetic
  fixture artifacts; normalized field scoring (casefold text,
  strict Decimal money, ISO dates, line-item exactness).
  Records `request_id`, `model_id`, latency, warnings. Default:
  NOT_TESTED, zero network calls.

## Live latency (opt-in)

- `phase5_benchmark.py --live --allow-billable` reuses
  `smoke_phase3` (one synthetic micro-request per provider, no
  retries) and folds each provider's observed status/HTTP/latency
  into the benchmark report. Budget: ≤4 calls (Spark, Voice, SAM,
  Baseten).

## Usage and cost

- Reported only when a provider reports it (`usage` objects,
  `video_frames_processed`). Pricing figures live in
  `META_API_CONTRACTS.md` as dated documentation context and are
  never hardcoded into tools. Estimates must cite the doc date;
  unavailable data stays unavailable — never fabricated.

## Reproduce

```powershell
.\.venv\Scripts\python.exe scripts\phase5_benchmark.py --cases 5
.\.venv\Scripts\python.exe scripts\phase5_eval.py
.\.venv\Scripts\python.exe scripts\phase5_live_smoke.py --live --allow-billable --max-calls 5
```
