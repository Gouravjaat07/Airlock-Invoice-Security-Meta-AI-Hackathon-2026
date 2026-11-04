# Hardware report — local Glimmer feasibility (Phase 1)

Source: `python scripts/check_hardware.py --json results/phase1/hardware.json`
on 2026-10-30 (forensic audit rerun). Structured evidence:
`results/phase1/hardware.json`. All disk/memory figures in GiB (unified).

## Observed hardware

| Fact | Observed value |
|---|---|
| Platform | Windows 11 (AMD64) |
| System RAM | 7.82 GiB total, 0.78 GiB available (GlobalMemoryStatusEx) |
| nvidia-smi | Not found (absence alone proves nothing) |
| Named graphics device | None — CIM video query is access-denied for the sandbox user (`Get-CimInstance : Access denied`, captured live), no other probe named one |
| CUDA / torch | Not installed; no inference runtime installed at all |
| Disk (project drive) | 90.46 GiB free of 138.47 GiB |
| Weight files in project | 0 |

## Decision: `LOCAL_GLIMMER_UNAVAILABLE`

No GPU was detected by any available probe (no nvidia-smi, no CUDA, no
named graphics device), no inference runtime is installed, and system RAM
is 7.82 GiB. Against the dossier planning estimates (~16.8 GiB weights +
~1.4 GiB projector, ~24 GiB VRAM working threshold — themselves unverified),
this machine has no viable local path for Glimmer 30B as observed.

Caveats recorded honestly:

- The CIM denial means GPU identity is *unknown*, not *proven absent*.
  But with 7.82 GiB system RAM and no CUDA stack, even an unreported
  integrated GPU would not change the decision — the gap is structural,
  not a measurement artifact.
- The dossier size/VRAM figures are still unverified against the official
  `meta-models/Muse-Glimmer-30B` artifacts (B-05). Verification matters
  for a future capable machine, not for this one.

## Consequence

The local-reader path is closed for this machine. Phase 2 proceeds with
the labelled fallback (hosted Spark reader with invoice-egress disclosure,
or a mock reader for deterministic-core tests) per FALLBACK_DECISIONS.md.
Kill Test 1's local-vs-hosted comparison requires capable hardware; do not
force it here.

## Storage note for a future capable machine

Staging needs remain estimates until B-05 closes: roughly 20+ GiB for
quantized weights + projector plus working margin (the audit uses a 30 GiB
free-disk margin). No download was started; none starts without verified
artifact identity and explicit size approval (AD-12).
