# Phase 3 — Privacy and security guide

## External data flow

Per inference call, exactly one artifact's bytes go to exactly one
configured provider: invoice PDF/image → extraction provider; voice
WAV → Meta ASR; delivery image/video → SAM. Sent alongside: task
instructions, JSON schema, concept noun phrase (SAM), session id
(voice, = internal op id). `store:false` on every Responses call;
inline media only (no Files API uploads, nothing retained
server-side to delete). No registry dumps, no PINs/sessions/
challenges, no bank keys, no unrelated identifiers. Bank references
appear only if printed on the invoice being extracted (unavoidable
for the task; local redaction before submission is a documented
future hardening step).

`store:false` disables response persistence, not provider-side
operational/billing logs. Review the provider's retention policy
before production use; Phase 3 acceptance uses synthetic data only.

## Credentials

Keys live in process env (`MODEL_API_KEY`, `BASETEN_API_KEY`,
optional `GLIMMER_API_KEY`), presence-only in every report,
validated at load (URLs must be https except loopback Glimmer, no
userinfo, contributor models refused, Meta≠Baseten keys). Never
logged, never in errors/audit (`check_secret_hygiene.py` enforced;
provider tests assert absence). Bearer [REDACTED] per request; TLS
verification never disabled.

## Logging and audit

Logs: status codes, latency, op ids, categories — never headers,
bodies, paths, SQL, or media. Audit: model/request ids, usage
(tokens only as returned — never cost estimates), attempts,
warnings, validation outcomes; never transcripts, lanes, payloads,
or keys. Observability writes never fabricate task success.

## Prompt injection

System/task instructions are versioned constants; untrusted bytes
travel only in user content parts / file parts. Tool calling is
never enabled; unexpected `function_call`/refusal/incomplete outputs
are rejected. Injection-shaped model values stay data through R1/R2/
R8 (`tests/adversarial/test_provider_injection.py`). The model can
touch nothing: no policy/registry/approval/payment/audit access.

## SSRF and URLs

Providers receive bytes, never URLs (no fetch targets, no redirects,
no metadata-service/DNS-rebinding surface). The only URLs in play
are operator-configured provider bases (validated) and the local
Glimmer endpoint (loopback http or https). Nothing is exposed to the
internet for inference.

## Residual risks

Provider-side logging/billing retention; historic Baseten key must
be treated as revoked (never used here); decoded mask rasters stay
in memory only (never persisted — counts alone are evidence);
Glimmer multimodal behavior runtime-dependent; bank text on
invoices necessarily transits the extractor; breaker/semaphore
state is process-local (multi-process deployments need external
coordination).
