# Phase 3 — Voice guide

Transcription (`muse-voice-transcribe-1.0`, file mode) feeds optional
delivery corroboration. Transcripts are T2 evidence for R7 voice
comparison only.

## Input

Strict gate before any request: RIFF/WAVE, mono, 16-bit integer PCM,
16 kHz or 24 kHz only (documented file-transcription rates), within
`max_audio_seconds` and upload caps. Anything else (stereo, float,
wrong rate, wrong container, corrupt/truncated header) is rejected
with a safe reason — never converted. No conversion tooling is
bundled (deliberate: avoids shell/ffmpeg attack surface); operators
must supply conforming WAV.

## Request and result

`POST /v1/asr/transcribe?sessionId=<op-id>`, multipart `request`
(`{mode: PUSH_TO_TALK (fixed), model, audioEncoding: WAV}`) + `audio`
file, `Accept: application/json`. Response validated: `transcript`
string (may be empty for silence), `turns[]` with integer
`turnId` (non-empty strings accepted defensively, normalized;
duplicates rejected), `startMs/endMs` (bounds-checked, end ≥ start),
`transcript`, optional `speaker`. Note `PUSH_TO_TALK` returns no
turns by design (single utterance). Turn-level timing only — no word
timing, no confidence scores exist in this API. Speaker labels are
session-scoped identifiers, never identity; never correlated across
recordings.

Realtime WebSocket mode is NOT implemented (no realtime product
requirement exists); adding it would need the full event-state
machine (turn ids, partials, speechEnd/speechComplete ordering).

## Pipeline use

`_gather_voice` compares the transcript against invoice facts
(`detect_voice_conflict`); conflicts feed R7 (ESCALATE), failures are
recorded and non-fatal. Voice can never authenticate, approve,
change banks/registry/policy, or satisfy a challenge. Audit
`voice.transcript` records chars/conflict/adapter/model/turn
count/request id/usage — never the transcript text.

## Limits

Language handling is provider-side; numeric/date words stay strings
until deterministic comparison (uncertain speech numbers never become
amounts). 500k-char transcript cap; 10k-turn cap.
