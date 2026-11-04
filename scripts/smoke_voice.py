"""Muse Voice Transcribe smoke test (Phase 1) — preflight only.

Intended Airlock role: transcription of an OPTIONAL supplier voice-note
artifact. Transcripts are untrusted data. Transcription is NOT authentication
and never proves speaker identity or approval.

The supported endpoint, audio format, and request schema have NOT been
verified against current provider documentation in this workspace. This script
validates inputs and records the blocker but REFUSES to transmit. Do not
record a real human voice without authorization; live tests require a
synthetic fixture in the exact documented format.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Mapping, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _smoke_common import (  # noqa: E402
    SmokeConfig, add_common_args, clamp_timeout, live_flag_misuse,
    live_requested_and_confirmed, mask_url_credentials, preflight,
    print_preflight_banner, save_record, utc_now_iso,
)

SCHEMA_VERIFIED = False
SCHEMA_DOCS_REF: Optional[str] = None

CONFIG = SmokeConfig(
    component="voice-transcribe",
    key_var="MODEL_API_KEY",
    base_url_default="",
    model_default="muse-voice-transcribe-1.0",
    description="Optional supplier voice-note transcription (schema UNVERIFIED).",
)

ALLOWED_AUDIO_SUFFIXES = (".wav", ".mp3", ".m4a", ".ogg")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Preflight (only) for Muse Voice Transcribe.")
    add_common_args(parser)
    parser.add_argument("--endpoint", default=None,
                        help="Fully verified transcription endpoint URL.")
    parser.add_argument("--audio", default=None,
                        help="Path to a synthetic audio fixture (must exist for live).")
    return parser


def main(argv: Optional[list[str]] = None,
         env: Optional[Mapping[str, str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    env = env if env is not None else os.environ
    base_url = args.base_url or args.endpoint or ""

    misuse = live_flag_misuse(args)
    if misuse:
        print(f"ERROR: {misuse}", file=sys.stderr)
        return 2

    if base_url:
        ok, messages = preflight(CONFIG, base_url, args.model or CONFIG.model_default, env)
    else:
        ok, messages = False, [
            f"{CONFIG.key_var} is {'set (value never shown)' if (env.get(CONFIG.key_var) or '').strip() else 'unset'}.",
            "No --endpoint/--base-url provided; no request target configured (expected: schema unverified).",
        ]
    if args.audio:
        audio_path = Path(args.audio)
        if not audio_path.is_file():
            ok = False
            messages.append(f"--audio file does not exist: {args.audio}")
        elif audio_path.suffix.lower() not in ALLOWED_AUDIO_SUFFIXES:
            ok = False
            messages.append(f"--audio has unexpected suffix {audio_path.suffix}; expected one of "
                            f"{', '.join(ALLOWED_AUDIO_SUFFIXES)} (exact documented format still "
                            "to be verified)")
        else:
            messages.append(f"--audio fixture exists: {args.audio}")
    messages.append("Request schema UNVERIFIED: endpoint, audio format, and payload are not "
                    "confirmed against current docs (see SOURCES.md).")
    print_preflight_banner(CONFIG, base_url or "(no endpoint)", args.model or CONFIG.model_default,
                           messages, ok and SCHEMA_VERIFIED)
    print("  Voice content is untrusted data; a transcript never authenticates anyone.")

    if not live_requested_and_confirmed(args):
        return 0

    timeout = clamp_timeout(args.timeout)
    record: dict = {"component": CONFIG.component, "test_type": "live-smoke",
                    "model_id": args.model or CONFIG.model_default,
                    "endpoint": mask_url_credentials(base_url) if base_url else None,
                    "timestamp_utc": utc_now_iso(),
                    "timeout_s": timeout, "audio": args.audio}
    if not SCHEMA_VERIFIED:
        record.update({"status": "NOT_TESTED", "http_status": None, "latency_ms": None,
                       "error_category": "schema-unverified",
                       "notes": "Refused to transmit: transcription endpoint/audio-format/payload "
                                "schema is not verified against current documentation. To unblock: "
                                "verify the docs, add a synthetic fixture in the exact documented "
                                "format, implement the payload builder with a citation, set "
                                "SCHEMA_VERIFIED=True. No request was sent."})
        saved = save_record(record, args.results_dir, args.json_path,
                            [(env.get(CONFIG.key_var) or "")])
        print(f"  Live result: NOT_TESTED ({record['error_category']})")
        print(f"  {record['notes']}")
        print(f"  Sanitized record saved to {saved}")
        return 1

    record.update({"status": "NOT_TESTED", "error_category": "not-implemented",
                   "notes": "Schema marked verified but no payload builder implemented."})
    print("ERROR: verified payload builder not implemented.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
