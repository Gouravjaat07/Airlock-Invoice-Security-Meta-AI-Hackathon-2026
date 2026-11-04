# SAM 3.1 setup (visual segmentation)

Delivery-evidence segmentation over the Responses API
(`stream:true`, SSE). Counts/boxes/masks are T2: a segmentation
count alone never proves delivery — R7 compares against invoiced
quantities with registry tolerance. Contract source:
`docs/integrations/META_API_CONTRACTS.md`.

## Configure

```powershell
$env:MODEL_API_KEY = "<meta-model-api-key>"
$env:AIRLOCK_VISION_PROVIDER = "sam"
# Optional overrides (defaults shown):
$env:SAM_MODEL = "sam-3.1"
$env:AIRLOCK_SAM_TIMEOUT_S = "300"
```

## Select + verify (no network)

```powershell
.\.venv\Scripts\python.exe scripts\phase5_live_smoke.py --provider meta-sam
```

## Live smoke (synthetic 8x8 image, streamed)

```powershell
.\.venv\Scripts\python.exe scripts\phase5_live_smoke.py --provider meta-sam --live --allow-billable
```

Empty lane + `response.completed` (zero matches) counts as success.

## Behavior notes

- Input: one short noun-phrase concept (first comma/semicolon/plus
  segment of the trusted catalogue label, max 120 chars) plus one
  `input_image` (PNG/JPEG) or `input_video` (MP4) part.
  The label always comes from the registry, never invoice text.
- Stream folded to the `output_text` lane; terminal
  `response.completed` required. Lane parsed by
  `app/providers/sam_parse.py`; masks decoded by
  `app/providers/sam_mask.py` (official codec port, budgets
  enforced before allocation: 4M px/mask, 16M px/lane).
- Validated: box coords, dims, ordinals, frame indices, mask
  encoding/size, truncation, unexpected tokens, completion.
  Malformed → `E_SCHEMA`; transport failure → `E_API_UNAVAILABLE`.
- Boxes capped at 500; raw mask payloads never reach the UI —
  only validated counts/boxes/areas through `SamEvidence`.

## Failure modes

| Symptom | Cause | Action |
|---|---|---|
| `missing_credential` | key unset | set `MODEL_API_KEY` |
| Stream never completes | network/provider stall | timeout aborts; case ERROR, retryable |
| `E_SCHEMA` on masks | grammar/codec mismatch | check `SAM_PROMPT_VERSION`, re-run offline SAM suites |
| Zero matches on clear images | concept phrasing | tune catalogue label segment; R7 escalates either way |
| 429 | 3000 RPM per-team | back off; frames bill per request (min 50/request) |
| `not_evaluated` record | delivery uploaded but vendor unresolved / catalogue empty | fix upstream; segmentation needs a trusted catalogue label |
