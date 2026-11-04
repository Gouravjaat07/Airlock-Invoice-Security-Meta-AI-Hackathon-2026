# Fallback decisions

Binding rules for every phase. A fallback must be LABELLED everywhere it
appears (logs, UI, records): silent substitution is a defect.

1. **Local Glimmer unsuitable** → use the documented hosted reader fallback
   (hosted Spark extraction, clearly labelled, invoice-egress disclosed) or
   a mock reader for local deterministic-core tests. Current state: Glimmer
   UNAVAILABLE on this machine → fallback is the default plan.
2. **Meta Model API unavailable** → develop the deterministic core against
   mocked model clients with recorded fixtures. No feature may depend on
   live Spark to be testable.
3. **SAM produces no useful count evidence** → remove the visual-
   corroboration claim and condition F from the evaluation. Never fabricate
   counts or masks; never treat "no detection" as proof of absence without
   a validated calibration.
4. **Voice Transcribe unavailable** → omit the voice-note workflow from the
   demonstrable version. No alternative transcription path may be smuggled
   in under the same status label.
5. **Baseten Spark Open unverifiable** → do not use a guessed deployment id.
   Mark NOT_TESTED/NOT_AVAILABLE; hosted-comparison experiments wait.
6. **Any model unavailable** → the application must NOT silently use another
   model under the same status label. Status, model id, and endpoint are
   recorded per request; a substitution is a new labelled configuration.
7. **Required verifier fails** → the verification FAILS. Error, timeout, or
   schema rejection is never coerced into success at any layer.
