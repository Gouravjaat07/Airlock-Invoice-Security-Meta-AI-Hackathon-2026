# Meta API contracts (Airlock Phase 5)

Checked: **2026-11-03** (delta re-verification; full verification
2026-11-01 in `docs/phase3/CAPABILITY_MATRIX.md`). Source of truth is
the official documentation below. No drift was found on this date:
every contract the adapters implement still matches the published
docs. Where a page below was recorded from structure + the 2026-11-01
read rather than a full re-read, it is marked accordingly.

## 1. Sources

| # | Document | URL | Checked |
|---|---|---|---|
| 1 | Overview | https://dev.meta.ai/docs/overview | 2026-11-03 (structure) |
| 2 | Models | https://dev.meta.ai/docs/models | 2026-11-03 (full read) |
| 3 | API reference | https://dev.meta.ai/docs/api-reference | 2026-11-01, nav re-seen 2026-11-03 |
| 4 | Choosing an API | https://dev.meta.ai/docs/protocols | 2026-11-01 |
| 5 | Responses API | https://dev.meta.ai/docs/protocols/responses | 2026-11-01 |
| 6 | File handling | https://dev.meta.ai/docs/file-handling | 2026-11-01 |
| 7 | Structured output | https://dev.meta.ai/docs/cookbook/structured-output | 2026-11-01 |
| 8 | Error handling | https://dev.meta.ai/docs/error-handling | 2026-11-03 (full read) |
| 9 | Pricing and rate limits | https://dev.meta.ai/docs/pricing-rate-limits | 2026-11-03 (full read) |
| 10 | Muse Voice | https://dev.meta.ai/docs/speech-to-text | 2026-11-03 (full read) |
| 11 | Voice API schemas | https://dev.meta.ai/docs/api-reference/voice/schemas | 2026-11-01 |
| 12 | SAM overview | https://dev.meta.ai/docs/sam/overview | 2026-11-03 (full read) |
| 13 | SAM API basics | https://dev.meta.ai/docs/cookbook/sam-api-basics | 2026-11-01 |
| 14 | Spark Open deploy | https://dev.meta.ai/docs/muse-spark-open/deploy | 2026-11-01 |
| 15 | Create a response | https://dev.meta.ai/docs/api-reference/responses/create-response | 2026-11-03 (full read) |

## 2. Base + auth (all hosted models)

- Base URL: `https://api.meta.ai/v1` (config `META_API_BASE`).
- Auth: `Authorization: Bearer $MODEL_API_KEY`; key format
  `LLM_{id}_{secret}`. OpenAI-compatible SDK surfaces supported.
- Standard mode (content not used for training) is the default;
  Contributor mode (`muse-spark-1.3-contributor`) trades content use
  for training for a discount. Airlock refuses `-contributor` model
  IDs in validated configuration and always uses Standard mode.

## 3. Muse Spark 1.3 (invoice extraction)

- Model: `muse-spark-1.3` (recommended for new work). Audio input is
  explicitly not fully supported — Airlock never routes audio to
  Spark; voice goes to Muse Voice Transcribe.
- Endpoint: `POST /v1/responses` (Responses API).
- Request: `{model, input, instructions?, text.format?, store?,
  max_output_tokens? (min 16), stream?}`. Airlock sends
  `instructions` + text/media input parts, `text.format` json_schema
  (`strict:false`), `store:false`, bounded `max_output_tokens`.
- Media: inline PDF (`input_file`) / images (`input_image`); inline
  ≤ 50 MB; Files API ≤ 1 GiB with `DELETE /v1/files/{id}`. Airlock
  sends inline only (app cap 10 MB) — no remote retention to manage.
- Response: output items `message|reasoning|function_call` with
  status; `usage{input_tokens,output_tokens,total_tokens}`;
  terminal `response.failed` carries `error{code,message}`.
  Airlock drops `reasoning`, rejects `function_call`, requires
  terminal `completed` for non-streaming calls.
- Adapter: `app/providers/spark.py` (`meta-spark/3.0.0`).

## 4. Muse Voice Transcribe (batch file mode)

- Model: `muse-voice-transcribe-1.0`.
- Endpoints: `POST https://api.meta.ai/v1/asr/transcribe`
  (multipart; `Authorization` header) for recordings;
  `wss://api.meta.ai/v1/asr/realtime` for live audio (auth in the
  handshake frame; the `Authorization` header is ignored).
- Airlock implements the file endpoint only; realtime is a
  documented non-goal (no live-microphone product workflow).
- Modes: `PUSH_TO_TALK` (default, single turn),
  `ENDPOINTING` (model turn boundaries), `DIARIZATION` (speaker
  labels `A`/`B`, session-scoped). Airlock sends `PUSH_TO_TALK`.
- Options: `keywords`, `languageBias` (25 languages + code-switch).
- Output: turn-level timestamps only. No word-level timestamps, no
  confidence scores, no sound-event/emotion detection. Events:
  `speechStart`, `transcript` (partials, no `turnId`), `speechEnd`
  (boundary only), `speechComplete` (authoritative turn text).
  Turns can overlap — key state on `turnId`.
- Adapter: `app/providers/voice.py` (`meta-voice/3.0.0`).

## 5. SAM 3.1 (visual segmentation)

- Model: `sam-3.1` over `POST /v1/responses` with the same Bearer
  [REDACTED] `stream:true` recommended for video; non-streaming
  returns the complete result.
- Input: one short `input_text` noun phrase per request (one
  concept; never concept+boxes mixed) plus one `input_image` or
  `input_video` part (MP4/MOV, H.264/H.265/MPEG-4).
- Output: `output_text` lane, one line per image/frame; per object
  an ordinal, a box (`x1;y1;x2;y2;w;h`, inclusive corners) and a
  mask (`x=0;y=0;data=H,W,enc+payload`, `~` lossless / `!`
  one_bit). Zero matches = empty lane + `response.completed`.
- Official parser: `@meta-sam/parser` (TypeScript). Airlock ports
  the mask codec to Python (`app/providers/sam_mask.py`) and the
  lane grammar to `app/providers/sam_parse.py`, with resource caps
  applied before allocation (fail closed).
- Adapter: `app/providers/sam.py` (`meta-sam/3.0.0`).

## 6. Baseten Muse Spark Open (alternate extraction)

- Hosted inference provider; OpenAI-compatible
  `POST {BASETEN_BASE_URL}/chat/completions` with
  `response_format` json_schema. Model:
  `meta-models/muse-spark-open-1026` (pinned 2026-11-03 per direct
  Baseten instruction; supersedes the `meta-models/muse-spark-open`
  value recorded in the 2026-11-01/03 doc verifications).
- The endpoint documents top-level `reasoning_effort`
  (`none|minimal|low|medium|high|xhigh|max`) and `max_tokens`
  (verified against the Baseten OpenAPI spec 2026-11-03); the
  smoke probe sends `reasoning_effort: "low"` + `max_tokens: 512`
  for this reasoning-capable model only.
- Separate credential (`BASETEN_API_KEY`, must differ from
  `MODEL_API_KEY`). Text+image parts; images only in Airlock
  (PDFs refused — Spark handles PDF input).
- Adapter: `app/providers/baseten.py` (`baseten-spark-open/3.0.0`)
  over the shared `app/providers/chat.py` core.

## 7. Muse Glimmer (optional local extraction)

- Open-weight multimodal model, distilled from Muse Spark; runs on
  operator hardware via vLLM/SGLang/llama.cpp/ExecuTorch over
  OpenAI-compatible `POST /chat/completions`. Default served name
  `muse-glimmer`; Airlock default endpoint
  `http://127.0.0.1:8081/v1` (plain http accepted for loopback
  only). No model download at startup; availability optional.
- Adapter: `app/providers/glimmer.py` (`glimmer-local/3.0.0`).

## 8. Error contract (drives `map_http_error`)

- Envelope: `{error:{message,type,param,code}}`; `message` is most
  reliable; `code` frequently `null` — branch on status, then
  `type`. `404` on unknown paths has an **empty body**.
- `401` → `authentication_error`/`invalid_api_key` (missing,
  malformed, revoked). `402` → `billing_error`
  (`billing_not_configured`). `403` → permission/feature denial.
- `404` on matched endpoints: `model_not_found` / `file_not_found`.
  (A `503` on model lookup is transient — retry, do not treat the
  model as missing.)
- `413` → `payload_too_large` (background body > 1 MiB;
  `store=true` persistence overflow — retry `store:false`, which
  Airlock already always sends).
- `429` → `rate_limit_error`/`rate_limit_exceeded` + `Retry-After`
  header; fix is exponential backoff with jitter.
- Retry transient only (429/5xx) with backoff + jitter; never
  retry 401/402/403/404/413 unchanged. `504`/`gateway_timeout`
  must NOT be retried (use streaming).
- Limits are per team: Spark 3000 RPM / 4M TPM; SAM 3000 RPM;
  Voice 256 concurrent streams / 16,000 streams per hour (shared
  realtime + file). Successful token responses carry
  `x-ratelimit-*` headers (Voice responses do not).

## 9. Pricing context (documentation only — never hardcoded)

- Spark: $1.25 input / $4.25 output per 1M tokens (Standard).
- Voice: $0.18 per audio hour, whole seconds.
- SAM: $2.50 per 1,000 images; $0.20 per 1,000 video frames
  (each video request billed for at least 50 frames;
  `usage.video_frames_processed` reports billed frames).
- Benchmarks must record the doc date with any estimate and
  distinguish reported usage from estimates.

## 10. Differences from the Phase 5 prompt

None material. The prompt's endpoints, model IDs, auth scheme, and
retry table all match the current docs. Two clarifications
recorded: (a) the realtime Voice endpoint authenticates in the
handshake frame, not the HTTP header (already documented in the
adapter as a non-goal); (b) 404 responses carry no JSON body, so
adapters must branch on status first (already implemented).
