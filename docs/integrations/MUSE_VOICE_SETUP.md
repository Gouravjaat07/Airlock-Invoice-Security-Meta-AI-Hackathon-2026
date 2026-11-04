# Muse Voice Transcribe setup (voice evidence)

Batch speech-to-text over `POST /v1/asr/transcribe` (multipart).
Transcripts are T2 corroboration only: voice never authenticates,
never approves, never edits trusted data. Contract source:
`docs/integrations/META_API_CONTRACTS.md`.

## Configure

```powershell
$env:MODEL_API_KEY = "<meta-model-api-key>"
$env:AIRLOCK_VOICE_PROVIDER = "meta"
# Optional overrides (defaults shown):
$env:VOICE_MODEL = "muse-voice-transcribe-1.0"
$env:AIRLOCK_VOICE_TIMEOUT_S = "300"
```

## Select + verify (no network)

```powershell
.\.venv\Scripts\python.exe scripts\phase5_live_smoke.py --provider meta-voice
```

## Live smoke (0.25 s synthetic silence)

```powershell
.\.venv\Scripts\python.exe scripts\phase5_live_smoke.py --provider meta-voice --live --allow-billable
```

## Behavior notes

- Audio gate first: WAV container, mono 16-bit PCM, 16 or 24 kHz
  (`app/providers/audio.py`). Anything else is rejected locally
  (`E_UPLOAD`) — never silently reinterpreted.
- Request: `request={mode:PUSH_TO_TALK, model, audioEncoding:WAV}`
  + `audio` file part. Response: `transcript` + optional `turns`
  (`turnId/startMs/endMs/transcript/speaker?`).
- Turn-level timestamps only. The API provides no word-level
  timestamps, confidence scores, emotion, or sound events; the
  adapter invents none of them.
- Voice failures are recorded, never fatal; conflicts feed R7
  (ESCALATE). Deterministic conflict signals: instruction-like
  markers, amount mismatches vs the invoice total, and PO /
  invoice reference tokens that differ from the extraction.
  Absent mentions never conflict.
- Transcription runs whenever a voice artifact is present — even
  when invoice extraction failed (the comparison is then skipped
  and the lane is `not_evaluated`, never clean). An empty
  transcript is recorded as `empty`: silence never confirms.
- Realtime WebSocket (`wss://.../asr/realtime`) is intentionally
  not implemented: the product has no live-microphone workflow.
  The file endpoint covers the voice-note evidence flow.

## Failure modes

| Symptom | Cause | Action |
|---|---|---|
| `missing_credential` | key unset | set `MODEL_API_KEY` |
| `E_UPLOAD` | non-WAV / stereo / bad rate | supply compliant WAV |
| 429 | stream limits (256 concurrent / 16k per hr) | back off; file + realtime share budget |
| Empty transcript | silence/unintelligible | existing R7 escalation path |
| Partial/garbled turns | audio quality | turns validated + deduped; malformed → `E_SCHEMA` |
