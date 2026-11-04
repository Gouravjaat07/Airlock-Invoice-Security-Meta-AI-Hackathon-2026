# Sources consulted (Phase 1)

Honesty rule: a source is listed as **read** only if it was opened in this
session. Search-result snippets are marked as such — they corroborate but do
not verify. Anything marked **not yet verified** must be checked directly
before the dependent Phase 2 work.

## Read in this session

1. **Hugging Face Transformers — MuseGlimmer model doc** (read 2026-10-30)
   [model_doc/muse_glimmer](https://huggingface.co/docs/transformers/main/model_doc/muse_glimmer)
   Confirms: repo id `meta-models/Muse-Glimmer-30B`, 30B dense multimodal
   (52-layer text decoder + frozen ViT-G/14), `image-text-to-text` pipeline
   usage, 131K context, `reasoning_strength` chat-template kwarg.
2. **LearnOpenCV — "SAM-3: What's New" (updated 2026-09-19)** (read 2026-10-30)
   [learnopencv.com/sam-3-whats-new](https://learnopencv.com/sam-3-whats-new/)
   Third-party tutorial reporting: SAM 3.1 Object Multiplex via Meta Model
   API; one coherent noun phrase per request (commas not a label list);
   `meta-sam-parser` PyPI package for mask decoding; key stored as
   `MODEL_API_KEY`; image $2.50/1k, video $0.20/1k frames (as checked
   2026-09-20); `404 model_not_found` for unauthorized teams.

## Corroborated by search snippets only (pages not opened)

3. Meta Model API base `https://api.meta.ai/v1` + `MODEL_API_KEY` convention —
   corroborated by a third-party client guide
   ([req_llm meta guide](https://github.com/agentjido/req_llm/blob/HEAD/guides/meta.md))
   describing an OpenAI-compatible API. Official docs not yet opened.
4. Baseten OpenAI-compatible endpoint `https://inference.baseten.co/v1` +
   `BASETEN_API_KEY` — corroborated by Docker docs and community mirrors of
   Baseten docs; official page: [Model APIs](https://docs.baseten.co/inference/model-apis/overview)
   (not yet opened).
5. Muse Glimmer Apache 2.0 licence — reported by several outlets (e.g.
   [OpenSourceForU](https://www.opensourceforu.com/2026/08/meta-open-sources-muse-glimmer/),
   [DataCamp](https://www.datacamp.com/blog/muse-glimmer)); the Hugging Face
   card / licence file itself has **not** been opened. Treat as unverified.
6. Muse Spark Open HF repo `meta-models/Muse-Spark-Open-816B-A42B` (gated) —
   reported by a [third-party guide](https://codersera.com/blog/muse-spark-open-complete-guide-2026/);
   unverified. The Baseten model id `meta-models/muse-spark-open` is a
   dossier default, unverified against the account deployment.
7. SAM 3 project pages (not opened): [ai.meta.com/sam3](https://ai.meta.com/sam3),
   [facebookresearch/sam3](https://github.com/facebookresearch/sam3),
   [meta-model-cookbook 07_sam](https://github.com/meta-models/meta-model-cookbook/blob/HEAD/07_sam/README.md).
   SAM custom licence terms reported by a fan site — unverified.

## Official pages to open before Phase 2 live work

- `https://dev.meta.ai/docs/authentication` — key creation, auth scheme.
- `https://dev.meta.ai/docs/sam/segmenting` — SAM request contract.
- `https://dev.meta.ai/docs/sam/reading-segmentation` — mask output format.
- `https://dev.meta.ai/docs/pricing-rate-limits` — confirm the 2M tok/min
  claim and SAM pricing against the actual account.
- `https://huggingface.co/meta-models/Muse-Glimmer-30B` — licence file,
  exact weight filenames, sizes.
- `https://docs.baseten.co/inference/model-apis/overview` — model slugs,
  readiness, rate limits for the account deployment.
- Muse Voice Transcribe endpoint/format — **no source found yet**; locate
  the official doc before any audio test design.

## Tooling references (standard knowledge, verified by local runs)

- Python `venv`/`pip`, pytest 8 (`pytest --version` run locally, 8.4.2).
- JSON Schema Draft 2020-12 vocabulary is used as declared in
  `eval/manifest.schema.json`; validation is implemented in stdlib-only
  `scripts/validate_manifest.py` (no external validator dependency).
- PowerShell CIM cmdlets and `nvidia-smi` used by `check_hardware.py`;
  absence is handled, not assumed.

## Uncertainty log

| Item | State |
|---|---|
| Meta chat-completions request shape for Spark 1.3 | Assumed OpenAI-compatible; official doc not opened |
| Structured/JSON-Schema output support on Meta API | Unknown |
| SAM hosted request/response schema | Partially described by tutorial; official doc not opened |
| Voice Transcribe endpoint/format | Unknown, no source located |
| Glimmer licence + exact artifact filenames | Reported Apache 2.0; primary not opened |
| Baseten deployment id, readiness, rate limit | Unknown until account checked |
| Muse Image / Muse Wonder relevance | Not researched (optional / out of scope) |
