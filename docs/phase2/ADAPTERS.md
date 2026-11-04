# Adapters (Phase 2 defaults)

All defaults are deterministic and offline (`app/adapters/`). No live
Meta, Baseten, SAM, or voice calls exist in Phase 2.

- **Fixture reader** (`readers.py`): serves ONLY artifacts whose
  SHA-256 is registered in the enabled fixtures directory
  (`AIRLOCK_FIXTURE_READER=1`, dev/test/demo). Anything else yields
  `E_READER_UNAVAILABLE` — by design, since live readers are
  unverified. Output is tainted T2 with fixture provenance; it never
  claims to be Muse Spark or Glimmer.
- **Mock SAM** (`vision.py`): returns a configured visible-instance
  count for a registry catalogue label (never invoice free text).
  Count-only evidence for R7; required only when delivery evidence is
  present. Records its limitations with every observation.
- **Mock ASR** (`transcription.py`): returns a configured transcript
  (tainted T2, length-bounded). Optional; failure never fails the case.
  Voice never authenticates and raw transcripts never reach the planner.
- **Template explainer** (`explanations.py`): renders the verdict +
  rule results into prose. Input boundary is verdict/rules only — the
  same boundary a future planner adapter must respect.
- **Mock executor** (`services/mock_payment_service.py`): the ONLY
  payment path. Local DB record, no network, always labelled
  `MOCK PAYMENT — NO MONEY TRANSFERRED`. No provider abstraction
  exists to misconfigure toward real rails.
