# Meta AI Integration

Date: 2026-11-04. All contracts below were read in code; live behavior
is contract-tested against mocks only (zero billable calls in this
mission). Setup guides: [Muse Spark](integrations/MUSE_SPARK_SETUP.md),
[Voice](integrations/MUSE_VOICE_SETUP.md), [SAM](integrations/SAM_SETUP.md),
[contracts](integrations/META_API_CONTRACTS.md).

## Role summary

| Model | Task | Input | Output | Downstream use |
|---|---|---|---|---|
| `muse-spark-1.3` (Responses API) | Invoice extraction | PDF/image bytes inline (base64 data URL) | Schema-constrained JSON (`invoice_extraction`) | Validated → T2 facts → deterministic R1–R10 |
| `meta-models/muse-spark-open-1026` (Baseten chat) | Same, alternate reader | Images only (PDF refused: no file part) | Same schema | Same path |
| `muse-glimmer` (loopback chat) | Same, local reader | Images only | Same schema | Same path |
| `muse-voice-transcribe-1.0` | Voice evidence | WAV (validated, ≤300 s) | Transcript + turns | Deterministic token/amount/PO/INV comparison → R7 |
| `sam-3.1` (Responses SSE) | Delivery segmentation | Image/MP4 + catalogue-noun concept | Mask-lane stream → count + boxes + areas | Count-vs-invoiced tolerance compare → R7 |

One provider per task, configured explicitly (`AIRLOCK_READER_PROVIDER`,
`AIRLOCK_VOICE_PROVIDER`, `AIRLOCK_VISION_PROVIDER`); failures raise,
never reroute.

## Muse Spark — invoice intelligence

- Contract: `app/providers/spark.py` (`meta-spark` 3.0.0) sends
  EXTRACTION_INSTRUCTIONS v5 + `text.format` JSON schema
  (`app/providers/prompts.py`), cap 4096 output tokens, 180 s timeout.
- Finalize (`providers/extraction.py`): 200 KB cap, field allowlist,
  alias rejection, ambiguous-currency drop, evidence-page grounding.
- Schema: `InvoiceExtraction` (`extra=forbid`), Decimal-only money,
  ISO dates, strict line items (`app/schemas/invoice.py`).
- Malformed/truncated output → R8 schema failure (DENY verdict), not a
  processing crash (`pipeline/process.py:_read_and_validate`).
- Provenance: adapter/model/prompt version + request_id + usage +
  warnings recorded in facts and audit.
- Why Spark: schema-constrained structured output over document images
  in one call; deterministic post-validation keeps it untrusted.
- Failure behavior: transport/auth/rate-limit/5xx mapped to categories,
  bounded retry (2), breaker; 402 billing surfaces distinctly.
- Evaluation: `score_extraction` per-field accuracy ready; live status
  NOT_TESTED. Repro: `tests/providers/test_meta_responses.py`,
  `test_extraction_contract.py`, `test_extraction_finalize.py`.

## Muse Voice Transcribe — voice evidence

- Contract: `app/providers/voice.py`; WAV-only (`providers/audio.py`
  parses + validates), push-to-talk mode constant, 300 s timeout.
- Empty transcript → EMPTY lane (never confirmation); provider failure
  → FAILED lane; both explicitly labeled end to end.
- Comparison is deterministic (`voice_conflict_details`): instruction
  markers, `PO-*`/`INV-*` token mismatch, `amount != total`. Absent
  mention is never a conflict.
- Malicious speech stays data: transcript is T2, instruction-like
  language escalates via R7, never authorizes.
- Provenance: adapter/model/turns/request_id/usage in the
  `voice.transcript` audit event.
- Evaluation: WER/CER defined + unit-tested
  (`app/evaluation/media_metrics.py`); live transcription NOT_TESTED;
  downstream conflict detection covered by `voice-instruction`
  scenario + `test_r7_voice_conflict_escalates`.

## SAM — visual evidence (geometry only)

- Contract: `app/providers/sam.py` + grammar (`sam_parse.py`) + mask
  codec (`sam_mask.py`); concept prompt built ONLY from the trusted
  catalogue label (`sam_concept_prompt`), never from invoice text.
- Output: track-aware count + bounded boxes + decoded mask areas.
  Never a product name, never a quantity verdict — R7 compares the
  count against invoiced quantities with catalogue tolerance.
- Fractional invoiced quantities cannot be count-compared → CONFLICT
  (honest, in `corroborate.py`).
- Empty stream → count compared (usually conflict); unevaluated bytes
  → NOT_EVALUATED with audit record.
- No classification or counting-accuracy claims: none are made in code,
  UI, or docs. Evaluation: count-error/MAE defined + unit-tested; live
  segmentation NOT_TESTED.

## Orchestration

```
reader → validate → resolve_vendor → [SAM lane ∥ voice lane]
→ corroborate → policy R1–R10 → verdict → proposal | review | rejected
```

Lanes run independently per case (`_gather_sam`, `_gather_voice`);
either may fail without hiding the other. Voice is always transcribed
when present; SAM needs a resolved vendor catalogue or it reports
NOT_EVALUATED. No model output reaches policy except through typed,
validated, compared values — and no model approves anything: verdicts
come from `evaluate_policy`, proposals from `propose.build_proposal`,
authorization from the owner.

## Deterministic vs model-generated

Model: extracted strings/numbers, transcripts, mask geometry.
Deterministic: normalization, fingerprints, arithmetic, dup keys, PO
math, comparisons, R1–R10, hashes, audit. The boundary is the T2 taint
label on every stored fact.

## Limitations

Live quality unevaluated for all three models; prompt v5 tuned against
fixtures, not adversarial live traffic; voice markers are heuristic;
SAM counts need integer quantities; Baseten/Glimmer readers are
image-only.
