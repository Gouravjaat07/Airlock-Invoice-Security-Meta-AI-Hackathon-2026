# Data flow and privacy (intended future architecture)

This document describes the INTENDED Phase 2+ design. Nothing here is
implemented in Phase 1. It exists so the build cannot accidentally violate
the trust model.

## Trust classes

- **T0** — authenticated owner input and authorized owner actions (proposal
  confirmation, PIN check). The only source of authorization.
- **T1** — trusted configuration, business policy, owner-managed vendor
  registry. Curated by the owner; versioned; never model-written.
- **T2** — untrusted model outputs, transcripts, visual evidence. May inform
  display and (validated) facts; may never authorize.
- **T3** — raw untrusted artifacts (uploaded PDFs, images, audio). Evidence
  only; handled through the controlled gateway.

Promotion rule: T3/T2 → trusted only via deterministic validation against
T0/T1 (registry match, arithmetic invariants, duplicate checks). Valid JSON
is NOT truth: schema validation ≠ truth validation. Two agreeing models
prove nothing. A failed verifier is a failed verification.

## Intended data flow (future pipeline)

1. Invoice images/PDFs → local Glimmer reader (**on-device**) when deployed.
2. Validated, typed, provenance-tagged facts → hosted Spark (advisory
   explanation only; cannot override deterministic verdicts).
3. Delivery images/video → hosted SAM when the visual check runs.
4. Voice notes → Voice Transcribe when the voice path runs.
5. PINs, session secrets, audit log → stay local, always.
6. If the local reader is unavailable and the hosted fallback reads the
   invoice, **invoice documents leave the device** — disclosed in the UI
   and logs, never silent.

The pipeline is NOT fully local even with Glimmer on-device. Any claim of
"on-device processing" must name exactly which stages, and which hosted
calls still occur.

## Authentication (future)

- Authenticated session + proposal-bound challenge + PIN per authorization.
- Voice transcription is never approval; transcripts never substitute for
  owner action; planner explanations never substitute for owner action.
- PIN stored as a password hash (Argon2/bcrypt); never plaintext; no
  default PIN ships. `AIRLOCK_PIN_HASH`/`AIRLOCK_SESSION_SECRET` stay empty
  until the auth service exists.

## Payments

Simulated only. No banking integrations, no real credentials, no real
financial data in any phase of the hackathon prototype.

## Development-session caution

Muse Code Contributor-mode content may be used for product improvement.
Do not paste real data, secrets, or confidential material into the dev
session. Runtime traffic must use `muse-spark-1.3`, never the Contributor
variant (enforced by `validate_config.py` and `smoke_meta.py`).
