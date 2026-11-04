"""Baseten / Muse Spark Open smoke test (Phase 1).

Default: preflight only, no external request.
Live (explicit opt-in): smallest synthetic text request against the configured
Baseten deployment.

Credit/rate-limit note: a reported balance or advertised limit does NOT prove
the deployment is ready. Live mode sends one minimal request only — no load
tests in Phase 1. Re-verify the base URL, model ID, and request shape against
the current account deployment and provider docs before any live use.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Callable, Mapping, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _smoke_common import (  # noqa: E402
    SmokeConfig, add_common_args, classify_error, clamp_timeout,
    live_flag_misuse, live_requested_and_confirmed, mask_url_credentials,
    post_json, preflight, print_preflight_banner, redact,
    sanitize_body_for_log, save_record, utc_now_iso,
)

CONFIG = SmokeConfig(
    component="baseten-spark-open",
    key_var="BASETEN_API_KEY",
    base_url_default="https://inference.baseten.co/v1",
    model_default="meta-models/muse-spark-open-1026",
    description="Minimal synthetic text completion against the Baseten Spark Open deployment.",
)

TEXT_PROMPT = "Reply with exactly: AIRLOCK_SMOKE_OK"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Preflight or live smoke test for Baseten Spark Open.")
    add_common_args(parser)
    return parser


def run_live(base_url: str, model: str, api_key: str, timeout: int,
             request_fn: Callable = post_json) -> dict:
    """Execute one minimal live request. Caller must have confirmed opt-in."""
    secrets = [api_key]
    payload = {"model": model,
               "messages": [{"role": "user", "content": TEXT_PROMPT}],
               "max_tokens": 16, "temperature": 0}
    record: dict = {"component": CONFIG.component, "test_type": "live-smoke",
                    "model_id": model, "endpoint": mask_url_credentials(base_url),
                    "timestamp_utc": utc_now_iso()}
    try:
        status, body, latency_ms = request_fn(
            f"{base_url.rstrip('/')}/chat/completions", payload, api_key, timeout)
    except Exception as exc:  # noqa: BLE001 - classify, never leak headers
        record.update({"status": "FAIL", "http_status": getattr(exc, "http_status", None),
                       "latency_ms": getattr(exc, "latency_ms", None),
                       "error_category": classify_error(exc),
                       "notes": redact(str(exc), secrets)[:300]})
        return record
    record.update({"status": "PASS", "http_status": status, "latency_ms": latency_ms,
                   "error_category": None,
                   "body_excerpt": sanitize_body_for_log(body, secrets),
                   "notes": "Synthetic text smoke test succeeded. This proves nothing about "
                            "rate limits, other modalities, or sustained availability."})
    return record


def main(argv: Optional[list[str]] = None,
         env: Optional[Mapping[str, str]] = None,
         request_fn: Callable = post_json) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    env = env if env is not None else os.environ
    base_url = args.base_url or CONFIG.base_url_default
    model = args.model or env.get("BASETEN_SPARK_OPEN_MODEL", "").strip() or CONFIG.model_default

    misuse = live_flag_misuse(args)
    if misuse:
        print(f"ERROR: {misuse}", file=sys.stderr)
        return 2

    ok, messages = preflight(CONFIG, base_url, model, env)
    print_preflight_banner(CONFIG, base_url, model, messages, ok)
    print("  Note: confirm the deployment ID, readiness, and rate limit in the Baseten "
          "account before live use. Do not spend significant credit on exploration.")

    if not live_requested_and_confirmed(args):
        return 0 if ok else 1

    if not ok:
        print("ERROR: preflight failed; no live request sent.", file=sys.stderr)
        return 1

    api_key = (env.get(CONFIG.key_var) or "").strip()
    timeout = clamp_timeout(args.timeout)
    print(f"  Live mode confirmed: sending ONE minimal synthetic request (timeout {timeout}s, no retries)...")
    record = run_live(base_url, model, api_key, timeout, request_fn)
    saved = save_record(record, args.results_dir, args.json_path, [api_key])
    print(f"  Live result: {record['status']} "
          f"(http={record.get('http_status')}, latency_ms={record.get('latency_ms')}, "
          f"error={record.get('error_category')})")
    print(f"  {record.get('notes')}")
    print(f"  Sanitized record saved to {saved}")
    return 0 if record["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
