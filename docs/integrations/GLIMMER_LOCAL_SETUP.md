# Muse Glimmer local setup (optional extraction)

Optional local/open-weight reader over any OpenAI-compatible
runtime (vLLM, SGLang, llama.cpp, Ollama, ExecuTorch). Not a core
dependency: Phase 5 never requires Glimmer to be available, and
the app never downloads weights.

## Configure

```powershell
$env:AIRLOCK_READER_PROVIDER = "glimmer"
# Optional overrides (defaults shown):
$env:GLIMMER_BASE_URL = "http://127.0.0.1:8081/v1"
$env:GLIMMER_MODEL = "muse-glimmer"
# Only if the local runtime requires authentication:
# $env:GLIMMER_API_KEY = "<local-key>"
```

Plain http is accepted for loopback hosts only; use https
otherwise. The served model name must match what the runtime
reports on `GET /models` (checked by `preflight()`).

## Serve weights (operator-run, outside Airlock)

1. Download weights per
   https://dev.meta.ai/docs/muse-glimmer/get-the-model and verify
   the checksum/license for your deployment.
2. Serve OpenAI-compatible HTTP, e.g. (vLLM):
   `vllm serve <weights> --host 127.0.0.1 --port 8081`.
3. Confirm the served model name equals `GLIMMER_MODEL`.

Hardware note: ~30B dense needs significant VRAM in bf16
(~72 GB) or ~17–20 GB quantized. If hardware is inadequate,
leave Glimmer unconfigured — report NOT RUN, never fake it.

## Verify (no model download, keyless-safe)

```powershell
.\.venv\Scripts\python.exe scripts\phase5_live_smoke.py --provider glimmer
.\.venv\Scripts\python.exe scripts\phase5_live_smoke.py --provider glimmer --live --allow-billable
```

The live probe is a `/models` check plus a minimal chat
round-trip. Reachability decides; quality needs a separate eval.

## Behavior notes

- Same shared chat core + finalizer + validation as Baseten.
- Multimodal (image-part) behavior is runtime-dependent and
  unverified here; the adapter sends standard parts and
  validates responses identically.
- Fail-closed like every provider: unreachable runtime →
  `E_API_UNAVAILABLE`; wrong served model → preflight reason.

## Failure modes

| Symptom | Cause | Action |
|---|---|---|
| Connection refused | runtime not running | start the runtime; keep Airlock unchanged |
| Served-model mismatch | wrong `--served-model-name` | align runtime name with `GLIMMER_MODEL` |
| OOM / slow tokens | hardware shortfall | quantize, smaller context, or stay unconfigured |
| `breaker_open` | repeated local failures | process-local; restart clears after fixing runtime |
