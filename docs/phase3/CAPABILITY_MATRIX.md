# Phase 3 — Provider capability matrix

Verified against official Meta Model API documentation on **2026-11-01**
(`https://dev.meta.ai/docs/...`; route set confirmed live this date).
Model IDs below are documentation records, not hardcoded values —
runtime code reads them from validated configuration.

## Model / provider matrix

| Model | Provider | Task in Airlock | Protocol | Auth | Status |
|---|---|---|---|---|---|
| `muse-spark-1.3` | Meta Model API (`META_API_BASE`) | Invoice/document extraction (structured) | Responses API `POST /v1/responses`, `text.format` json_schema, `store:false`, inline `input_file` PDF/image | `Authorization` header with `MODEL_API_KEY` | Code + offline tests; live NOT TESTED (no key) |
| `muse-voice-transcribe-1.0` | Meta Model API | WAV transcription (file mode) | `POST /v1/asr/transcribe?sessionId=` multipart (`request` JSON + `audio`); modes PUSH_TO_TALK/ENDPOINTING/DIARIZATION | Bearer header | Code + offline tests; live NOT TESTED |
| `sam-3.1` | Meta Model API | Delivery image/video segmentation (concept noun phrase) | Responses API `stream:true` SSE, special-token lane grammar (one line/frame, box+mask records) | Bearer header | Code + offline tests; live NOT TESTED |
| `meta-models/muse-spark-open` | Baseten (`BASETEN_BASE_URL`) | Alternate extraction route | OpenAI-compatible `POST /chat/completions`, `response_format` json_schema, `image_url` parts | Auth header with `BASETEN_API_KEY` | Code + offline tests; live BLOCKED (historic key untrusted per spec §18.2) |
| `muse-glimmer` (served name) | Local runtime (`GLIMMER_BASE_URL`) | Optional local extraction | OpenAI-compatible `POST /chat/completions` (vLLM/SGLang/llama.cpp/Ollama all serve this) | Optional, runtime-dependent | Code + offline tests; live NOT AVAILABLE (no local runtime here) |
| `muse-image-1.0` | — | NONE (deliberately excluded) | — | — | NOT APPLICABLE: generative output must never be evidence (§13.1) |
| `muse-wonder-1.0` | — | NONE (no justified use case) | — | — | NOT IMPLEMENTED by decision (§13.2) |

Never configured: `muse-spark-1.3-contributor` (dev-assistance only).

## Verified contract facts (2026-11-01)

- Base `https://api.meta.ai/v1`; per-team rate limits; auth is a
  bearer-style `Authorization` header (key format per provider docs).
- Responses: `{model, input, instructions?, text.format?, store?, max_output_tokens? (min 16), stream?}`; output items `message|reasoning|function_call` with `status`; `usage{input_tokens,output_tokens,total_tokens}`; terminal `response.failed` carries `error{code,message}`; cancel/retrieve/delete endpoints exist.
- Structured output: Responses uses `text.format`, Chat Completions uses `response_format`; no recursive schemas (400); unsupported params (`stop`, penalties, `n>1`, logprobs on Spark) must be omitted.
- Files: inline ≤50 MB (`file_data`/`input_file`/`image_url` data URLs); Files API ≤1 GiB + `DELETE /v1/files/{id}`; PDF → text (first 100 pp) + page images (first 50); ≤50 images/request. **Airlock sends inline only** (app cap 10 MB) — no server-side file retention to manage.
- Voice file contract: RIFF/WAVE mono 16-bit PCM @16/24 kHz; body ≤32 MB; audio ≤10 min; JSON `{sessionId, transcript, audioDurationMs, turns[{turnId(int),startMs,endMs,transcript,speaker?}]}`; `PUSH_TO_TALK` returns no turns (single utterance); turn-level timestamps only, no confidence/word timing; labels session-scoped; realtime is WS-only (not implemented — no realtime requirement).
- SAM: `input_text` noun phrase (one concept/request; never concept+boxes mixed) + `input_image(image_url)` / `input_video(video_url|file_id)`; zero matches = empty lane + `response.completed` (normal); object ids integer, sparse, stable per response; frame indices zero-based, may skip or run out of order; inclusive box corners; mask origin literal `x=0;y=0`; masks official-base85 `~`lossless/`!`one_bit, H-first rasters; `metadata.mask_encoding` + `metadata.include_confidence` supported.
- Errors: `{error:{message,type,param,code}}` (`code` often null — branch on status, then `type`); 404 has empty body; 429/503 carry `Retry-After`; retry transient only with backoff + jitter; 504/`gateway_timeout` must NOT be retried (use streaming); 402 `billing_error` needs an operator; mid-stream terminal `error` events are retryable; codes incl. `invalid_api_key`, `model_not_found`, `rate_limit_exceeded`, `payload_too_large`, `gateway_timeout`, `content_policy_violation`, `server_shutting_down`, `service_overloaded`, `backend_unavailable`, `billing_not_configured`.
- Baseten: OpenAI-compatible chat/completions; text+image+video+audio parts; media >~74 MB by URL; video ≤200 MB/300 s by URL; ≤96 frames sampled.
- Glimmer: 30B dense (~72 GB VRAM bf16; 17–20 GB quantized); OpenAI-compatible HTTP on all listed runtimes; default served name `muse-glimmer`; localhost default port varies by runtime (Airlock default `http://127.0.0.1:8081/v1` preserved).
- Voice pricing observed ($0.18/audio-hr) is documentation context only — never hardcoded, never used for estimates without a live usage record.

## Open / unverified items

- `text.format` exact JSON-Schema wrapper shape is implemented per the OpenAI-compatible Responses convention (`text.format{type:json_schema,name,schema,strict}`) with `strict: false` (the strict subset forbids the dynamic evidence map; output is still schema-constrained; local validation authoritative); live round-trip NOT TESTED (no credential).
- SAM mask rasters decode with the official codec port (`sam_mask.py`, verified against the published `@meta-sam/parser` 0.1.0 sources + hand-computed vectors); live round-trip NOT TESTED (no credential). R7 consumes counts/boxes/decoded areas only.
- Glimmer multimodal (image-part) behavior is runtime-dependent and unverified here; adapter sends standard parts and validates responses the same as Spark.
