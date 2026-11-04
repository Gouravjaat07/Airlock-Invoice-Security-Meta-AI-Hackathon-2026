"""Meta Spark 1.3 smoke test (Phase 1).

Default: preflight only, no external request.
Live (explicit opt-in): smallest synthetic text request, then — only after the
text test succeeds and only with --structured — a structured-output request.

Request shape note: the chat-completions JSON below follows the widely
documented OpenAI-compatible pattern. Re-verify against the current Meta Model
API documentation before any live use; a working text request does NOT prove
structured/JSON-Schema output works.
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
    component="meta-spark",
    key_var="MODEL_API_KEY",
    base_url_default="https://api.meta.ai/v1",
    model_default="muse-spark-1.3",
    description="Minimal synthetic text completion against hosted Muse Spark 1.3.",
)

CONTRIBUTOR_MODEL = "muse-spark-1.3-contributor"
TEXT_PROMPT = "Reply with exactly: AIRLOCK_SMOKE_OK"
STRUCTURED_PROMPT = 'Reply with exactly this JSON object and nothing else: {"smoke": "ok"}'


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Preflight or live smoke test for Meta Spark 1.3.")
    add_common_args(parser)
    parser.add_argument("--structured", action="store_true",
                        help="After a successful text test, also run a structured-output test.")
    return parser


def run_text_test(base_url: str, model: str, api_key: str, timeout: int,
                  request_fn: Callable = post_json) -> dict:
    payload = {"model": model,
               "messages": [{"role": "user", "content": TEXT_PROMPT}],
               "max_tokens": 16, "temperature": 0}
    return request_fn(f"{base_url.rstrip('/')}/chat/completions", payload, api_key, timeout)


def run_structured_test(base_url: str, model: str, api_key: str, timeout: int,
                        request_fn: Callable = post_json) -> dict:
    payload = {"model": model,
               "messages": [{"role": "user", "content": STRUCTURED_PROMPT}],
               "max_tokens": 64, "temperature": 0,
               "response_format": {"type": "json_object"}}
    return request_fn(f"{base_url.rstrip('/')}/chat/completions", payload, api_key, timeout)


def run_live(base_url: str, model: str, api_key: str, timeout: int,
             structured: bool, request_fn: Callable = post_json) -> dict:
    """Execute live request(s). Caller must have confirmed explicit opt-in."""
    secrets = [api_key]
    record: dict = {"component": CONFIG.component, "test_type": "live-smoke",
                    "model_id": model, "endpoint": mask_url_credentials(base_url),
                    "timestamp_utc": utc_now_iso(), "requests": []}
    try:
        status, body, latency_ms = run_text_test(base_url, model, api_key, timeout, request_fn)
    except Exception as exc:  # noqa: BLE001 - classify, never leak headers
        record.update({"status": "FAIL", "http_status": getattr(exc, "http_status", None),
                       "latency_ms": getattr(exc, "latency_ms", None),
                       "error_category": classify_error(exc),
                       "notes": redact(str(exc), secrets)[:300]})
        return record
    record["requests"].append({"kind": "text", "http_status": status,
                               "latency_ms": latency_ms,
                               "body_excerpt": sanitize_body_for_log(body, secrets)})
    record.update({"status": "PASS", "http_status": status, "latency_ms": latency_ms,
                   "error_category": None,
                   "notes": "Synthetic text smoke test succeeded."})

    if structured:
        try:
            status2, body2, latency2 = run_structured_test(
                base_url, model, api_key, timeout, request_fn)
        except Exception as exc:  # noqa: BLE001
            record["requests"].append({"kind": "structured", "http_status": None,
                                       "error_category": classify_error(exc)})
            record["notes"] += (" Structured-output follow-up FAILED "
                                f"({classify_error(exc)}); text success does not imply "
                                "structured-output support.")
            return record
        record["requests"].append({"kind": "structured", "http_status": status2,
                                   "latency_ms": latency2,
                                   "body_excerpt": sanitize_body_for_log(body2, secrets)})
        record["notes"] += " Structured-output follow-up also succeeded."
    else:
        record["notes"] += " Structured output NOT tested in this run."
    return record


def main(argv: Optional[list[str]] = None,
         env: Optional[Mapping[str, str]] = None,
         request_fn: Callable = post_json) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    env = env if env is not None else os.environ
    base_url = args.base_url or CONFIG.base_url_default
    model = args.model or env.get("SPARK_MODEL", "").strip() or CONFIG.model_default

    misuse = live_flag_misuse(args)
    if misuse:
        print(f"ERROR: {misuse}", file=sys.stderr)
        return 2

    ok, messages = preflight(CONFIG, base_url, model, env)
    if model == CONTRIBUTOR_MODEL:
        ok = False
        messages.append("Refusing: `muse-spark-1.3-contributor` is for development assistance "
                        "only and must never be used for Airlock runtime data.")
    print_preflight_banner(CONFIG, base_url, model, messages, ok)
    print("  Note: re-verify the request shape against current Meta Model API docs before live use.")

    if not live_requested_and_confirmed(args):
        return 0 if ok else 1

    if not ok:
        print("ERROR: preflight failed; no live request sent.", file=sys.stderr)
        return 1

    api_key = (env.get(CONFIG.key_var) or "").strip()
    timeout = clamp_timeout(args.timeout)
    print(f"  Live mode confirmed: sending minimal synthetic request (timeout {timeout}s, no retries)...")
    record = run_live(base_url, model, api_key, timeout, args.structured, request_fn)
    saved = save_record(record, args.results_dir, args.json_path, [api_key])
    print(f"  Live result: {record['status']} "
          f"(http={record.get('http_status')}, latency_ms={record.get('latency_ms')}, "
          f"error={record.get('error_category')})")
    print(f"  {record.get('notes')}")
    print(f"  Sanitized record saved to {saved}")
    return 0 if record["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
