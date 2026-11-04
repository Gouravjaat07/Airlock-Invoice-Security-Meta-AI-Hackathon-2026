# Phase 3 — SAM guide

SAM 3.1 provides delivery geometry (boxes + track-aware counts) for
R7. It is not a verifier: R7 keeps its deterministic semantics and a
SAM count alone never satisfies it.

## Requests

One concept per request: the noun phrase comes from the trusted
catalogue label (`sam_concept_prompt`: first phrase, bounded,
single line). Never concept+boxes mixed, never commands/questions.
Image → `input_image` data URL; MP4 → `input_video` data URL
(app caps bound the body; provider inline limit is 50 MB).
`stream:true`, `store:false`, `metadata.mask_encoding: one_bit`
(compact; the parser still reads the per-record marker — a
`lossless` record is accepted, never assumed away).

## Parsing

`sam_parse.py` implements the documented lane grammar strictly: one
line per frame, `<Nf>` markers, comma-separated records, each an
integer object id plus exactly one box token then exactly one mask
token. Box corners are inclusive source pixels; the mask origin is
the literal `x=0;y=0`; confidence rides only in `;c=` token fields.
Every box is bounds-checked against the reported media size; media
size must be single-valued per lane and (for images) must equal the
artifact's parsed dimensions; each raster must fit its frame.

`sam_mask.py` decodes every mask raster with a line-by-line port of
the official `@meta-sam/parser` 0.1.0 `mask-codec.js` (base85 with
the official 85-char alphabet, range-coded one_bit/lossless planes,
canonical-form checks), plus Airlock budgets applied before any
allocation (4M px/mask, 16M px/lane). An undecodable mask is invalid
evidence, never a silent pass. Any deviation → schema failure → R9
DENY path (same as mock-verifier errors).

## Counting

Count = distinct object ids across all frames (track-aware; ids are
stable per response). Never per-frame sums. Zero matches (empty
lane + completed) is a valid count of 0. The configured
`sam_count_min/max` range is enforced; violations fail the verifier.
Occlusion, fragmentation, merged tracks, and category ambiguity all
resolve the same way: the count either reconciles within tolerance
or R7 escalates — uncertainty never confirms quantity.

## Evidence

`SamEvidence` carries count, frames observed, up to 500 boxes
(object/frame/coords/decoded mask area + set-pixel count;
truncation warned), request id, model, usage, warnings. Audit
`sam.evidence` stores count/frames/box-count (not full geometry)
plus provenance. Mask payloads and decoded rasters are never
persisted — only the derived counts.
