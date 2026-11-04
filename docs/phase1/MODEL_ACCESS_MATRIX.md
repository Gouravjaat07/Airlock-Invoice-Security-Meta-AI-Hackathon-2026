# Model access matrix (Phase 1)

One row per integration. "Evidence" is what exists IN THIS WORKSPACE;
user-reported prior testing is noted, never counted as verification.

| Target | Credential / route | Status | Evidence here | Blocker to verify |
|---|---|---|---|---|
| Muse Code (dev tool) | CLI install | PASS (presence) | `muse --version` → 1.4.14 | None |
| Spark 1.3 (advise/baseline) | `MODEL_API_KEY` → api.meta.ai/v1 | USER_REPORTED_TESTED, NOT_REPRODUCED | None; key unset | Set key, opt-in live text test |
| Glimmer 30B (local reader) | Local weights + runtime | NOT_INTEGRATED; hw UNAVAILABLE | No GPU, no runtime, no weights | Hardware + verified artifacts |
| SAM 3.1 (visual count) | `MODEL_API_KEY` → Meta API (hosted) | NOT_TESTED | Schema unverified, refusal path tested | Open official SAM docs, build payload |
| Voice Transcribe | `MODEL_API_KEY` → unknown endpoint | NOT_TESTED | No source, no fixture | Locate official doc + format |
| Spark Open (Baseten) | `BASETEN_API_KEY` → inference.baseten.co/v1 | USER_REPORTED_TESTED, NOT_REPRODUCED | None; key unset | Confirm deployment, 1 minimal call |
| Muse Image (fixtures) | Unknown | NOT_TESTED | Not researched | Decide necessity first |
| Muse Wonder | N/A | NOT_INTEGRATED | Out of scope | Needs evaluation reason |

## Provider detail (Phase 1 scope)

| Target | Config vars | Base URL (default) | Model ID (default) | Auth | Timeout | Retry | Live / mock | Required? |
|---|---|---|---|---|---|---|---|---|
| Spark 1.3 | `MODEL_API_KEY`, `META_API_BASE`, `SPARK_MODEL` | `https://api.meta.ai/v1` | `muse-spark-1.3` | Bearer key | 30s (max 120s) | none (bound 0) | preflight verified; live `NOT_TESTED` | yes |
| Spark Open (Baseten) | `BASETEN_API_KEY`, `BASETEN_BASE_URL`, `BASETEN_SPARK_OPEN_MODEL` | `https://inference.baseten.co/v1` | `meta-models/muse-spark-open` | Bearer key | 30s (max 120s) | none (bound 0) | preflight verified; live `NOT_TESTED` | yes |
| SAM 3.1 | `MODEL_API_KEY`, `--endpoint` | none (unverified) | `sam-3.1` | n/a (refuses) | recorded only | none | live refused: schema unverified | conditional |
| Voice Transcribe | `MODEL_API_KEY`, `--endpoint`, `--audio` | none (unverified) | `muse-voice-transcribe` | n/a (refuses) | recorded only | none | live refused: schema unverified | optional |
| Glimmer 30B (local) | `GLIMMER_BASE_URL` | `http://127.0.0.1:8081/v1` (loopback) | local weights (none staged) | none (local) | n/a | n/a | `NOT_INTEGRATED`; hw `UNAVAILABLE` | conditional (fallback active) |

Request contract notes (all unverified against current provider docs until a
live run succeeds): Meta/Baseten use one OpenAI-compatible
`POST {base}/chat/completions` call (`max_tokens: 16`, `temperature: 0`,
synthetic `AIRLOCK_SMOKE_OK` prompt); Meta accepts an optional second
structured call (`max_tokens: 64`, JSON object) only after the text call
passes. SAM/voice have no payload builder: live mode records `NOT_TESTED`
with `schema-unverified` and transmits nothing. All live paths require
`--live --allow-billable`, enforce HTTPS except loopback test endpoints,
classify 401/403 as auth errors, 408 as timeout, 429 as rate-limited
(no backoff, no retry), and 5xx as server errors. Prior user-reported
testing stays `USER_REPORTED_TESTED` and is never auto-upgraded.

## Credential separation

- `MODEL_API_KEY` (Meta) and `BASETEN_API_KEY` (Baseten) are distinct;
  `validate_config.py` errors if they share a value.
- No key is set in this session; no key appears in any report or log.
- Runtime model must be `muse-spark-1.3`; the Contributor variant is
  refused for runtime use by config validation and the Meta smoke test.
