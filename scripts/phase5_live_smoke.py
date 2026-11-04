"""Phase 5 provider live smoke (bounded, explicit opt-in only).

Thin Phase 5 entry point over the shared smoke runner in
`scripts/smoke_phase3.py`: same safety contract (preflight default,
`--live --allow-billable` required, `--max-calls` budget, synthetic
inputs only, sanitized records), with Phase 5 evidence stored under
`results/phase5/`. There is exactly one smoke implementation; this
module only relocates the default evidence directory and labels the
run for Phase 5.

Usage:
  python scripts/phase5_live_smoke.py [--provider all|meta-spark|meta-voice|meta-sam|baseten|glimmer]
  python scripts/phase5_live_smoke.py --live --allow-billable [--max-calls 3]
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable, Mapping, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

import smoke_phase3 as smoke  # noqa: E402

RESULTS_DIR = "results/phase5"


def build_parser():  # noqa: ANN201, ANN202 - delegated parser type
    parser = smoke.build_parser()
    parser.description = "Phase 5 provider live smoke."
    parser.set_defaults(results_dir=RESULTS_DIR)
    return parser


def main(argv: Optional[list[str]] = None,
         env: Optional[Mapping[str, str]] = None,
         live_runner: Optional[Callable] = None) -> int:
    """Entry point. `live_runner` is a test double (see smoke_phase3)."""
    args = list(sys.argv[1:] if argv is None else argv)
    if not any(arg == "--results-dir" or arg.startswith("--results-dir=")
               for arg in args):
        args += ["--results-dir", RESULTS_DIR]
    print("Phase 5 live smoke (shared runner: scripts/smoke_phase3.py).")
    return smoke.main(args, env=env, live_runner=live_runner)


if __name__ == "__main__":
    raise SystemExit(main())
