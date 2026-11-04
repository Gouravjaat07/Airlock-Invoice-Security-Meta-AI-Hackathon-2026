"""Shared helpers for Airlock smoke-test utilities (Phase 1).

Safety contract (enforced by every smoke_* script):
  * Default invocation performs preflight only — never a network request.
  * Live mode requires BOTH --live and --allow-billable.
    (--confirm-external-call is a deprecated alias of --allow-billable.)
  * Smallest practical request, strict timeout, no automatic retries.
  * HTTPS required, except documented loopback test endpoints
    (localhost / 127.0.0.1 / ::1 over plain http).
  * Synthetic content only; sanitized logs; secrets never printed or stored.
"""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Optional
from urllib.parse import urlparse, urlsplit, urlunsplit

from _common import atomic_write_json

DEFAULT_TIMEOUT_S = 30
MAX_TIMEOUT_S = 120
REDACTED = "***REDACTED***"


@dataclass
class SmokeConfig:
    component: str          # e.g. "meta-spark"
    key_var: str            # env var holding the credential
    base_url_default: str
    model_default: str
    description: str        # what a live test would do


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--live", action="store_true",
                        help="Perform a real external request (requires --allow-billable).")
    parser.add_argument("--allow-billable", "--confirm-external-call",
                        dest="confirm_external_call", action="store_true",
                        help="Explicit confirmation that an external, possibly billable call "
                             "is intended. --allow-billable is canonical; "
                             "--confirm-external-call is a deprecated alias.")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_S,
                        help=f"Strict request timeout in seconds (default {DEFAULT_TIMEOUT_S}, max {MAX_TIMEOUT_S}).")
    parser.add_argument("--base-url", default=None, help="Override the default base URL.")
    parser.add_argument("--model", default=None, help="Override the default model ID.")
    parser.add_argument("--json", dest="json_path", default=None,
                        help="Write the sanitized result record as JSON to this path.")
    parser.add_argument("--results-dir", default="results/phase1",
                        help="Directory for auto-saved live-test records.")


def live_requested_and_confirmed(args: argparse.Namespace) -> bool:
    return bool(args.live and args.confirm_external_call)


def live_flag_misuse(args: argparse.Namespace) -> Optional[str]:
    """Return an error message if live flags are partially given, else None."""
    if args.live and not args.confirm_external_call:
        return ("Refusing: --live was given without --allow-billable. "
                "No request was sent. Re-run with both flags to opt in explicitly.")
    if args.confirm_external_call and not args.live:
        return ("Refusing: --allow-billable was given without --live. "
                "No request was sent.")
    return None


def clamp_timeout(value: int) -> int:
    if value <= 0:
        return DEFAULT_TIMEOUT_S
    return min(value, MAX_TIMEOUT_S)


def is_valid_http_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def url_https_policy_ok(value: str) -> bool:
    """True for https URLs, or plain-http loopback test endpoints only."""
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    if parsed.scheme == "https":
        return True
    if parsed.scheme != "http":
        return False
    try:
        host = (parsed.hostname or "").lower()
    except ValueError:
        return False
    return host in ("localhost", "127.0.0.1", "::1")


def mask_url_credentials(url: str) -> str:
    """Replace URL userinfo (user:pass@) with ***; host/port/path preserved."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    user, sep, hostport = parts.netloc.rpartition("@")
    if not sep or not user:
        return url
    return urlunsplit((parts.scheme, "***@" + hostport, parts.path,
                       parts.query, parts.fragment))


def redact(text: str, secrets: list[str]) -> str:
    for secret in secrets:
        if secret and len(secret) >= 4 and secret in text:
            text = text.replace(secret, REDACTED)
    return text


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def preflight(config: SmokeConfig, base_url: str, model: str,
              env: Optional[Mapping[str, str]] = None) -> tuple[bool, list[str]]:
    """Validate configuration without any network I/O. Returns (ok, messages)."""
    env = env if env is not None else os.environ
    messages: list[str] = []
    ok = True

    key = (env.get(config.key_var) or "").strip()
    if not key:
        ok = False
        messages.append(f"{config.key_var} is unset: live test unavailable (preflight only).")
    else:
        messages.append(f"{config.key_var} is set (value never shown).")

    if not is_valid_http_url(base_url):
        ok = False
        messages.append(f"Base URL is not a valid http(s) URL: {mask_url_credentials(base_url)}")
    elif not url_https_policy_ok(base_url):
        ok = False
        messages.append("Base URL uses plain http outside loopback: rejected "
                        "(https required except documented loopback test endpoints).")
    else:
        messages.append(f"Base URL syntax OK: {mask_url_credentials(base_url)}")

    if not model.strip():
        ok = False
        messages.append("Model ID is empty.")
    else:
        messages.append(f"Model ID: {model}")

    return ok, messages


def post_json(url: str, payload: dict, api_key: str, timeout: int,
              extra_headers: Optional[dict] = None) -> tuple[Optional[int], str, int]:
    """Single POST with no retries. Returns (http_status, body_text, latency_ms).

    Raises SmokeRequestError on transport failure. Never logs the key.
    """
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json",
               "Authorization": f"Bearer {api_key}"}
    if extra_headers:
        headers.update(extra_headers)
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            latency_ms = int((time.perf_counter() - start) * 1000)
            return response.status, response.read().decode("utf-8", "replace"), latency_ms
    except urllib.error.HTTPError as exc:
        latency_ms = int((time.perf_counter() - start) * 1000)
        try:
            text = exc.read().decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            text = ""
        raise SmokeRequestError(f"HTTP {exc.code}", http_status=exc.code,
                                body=text, latency_ms=latency_ms) from exc
    except urllib.error.URLError as exc:
        latency_ms = int((time.perf_counter() - start) * 1000)
        raise SmokeRequestError(f"URL error: {exc.reason}", latency_ms=latency_ms) from exc
    except TimeoutError as exc:
        latency_ms = int((time.perf_counter() - start) * 1000)
        raise SmokeRequestError(f"timed out after {timeout}s", latency_ms=latency_ms) from exc
    except OSError as exc:
        latency_ms = int((time.perf_counter() - start) * 1000)
        raise SmokeRequestError(f"connection failed: {exc}", latency_ms=latency_ms) from exc


class SmokeRequestError(Exception):
    def __init__(self, message: str, http_status: Optional[int] = None,
                 body: str = "", latency_ms: int = 0):
        super().__init__(message)
        self.http_status = http_status
        self.body = body
        self.latency_ms = latency_ms


def sanitize_body_for_log(body: str, secrets: list[str], limit: int = 500) -> str:
    text = redact(body, secrets)
    if len(text) > limit:
        text = text[:limit] + f"... [truncated, {len(body)} chars total]"
    return text


def classify_error(exc: BaseException) -> str:
    name = type(exc).__name__
    message = str(exc).lower()
    if isinstance(exc, SmokeRequestError):
        if exc.http_status in (401, 403) or "unauthorized" in message or "forbidden" in message:
            return "auth-error"
        if exc.http_status == 404:
            return "not-found"
        if exc.http_status in (400, 422):
            return "bad-request"
        if exc.http_status == 408:
            return "timeout"
        if exc.http_status == 413:
            return "payload-too-large"
        if exc.http_status == 429:
            return "rate-limited"
        if exc.http_status and 500 <= exc.http_status < 600:
            return "server-error"
        if "timed out" in message or "timeout" in message:
            return "timeout"
        if "url error" in message or "connection failed" in message:
            return "connection-error"
        return "http-error"
    if "timeout" in message:
        return "timeout"
    return f"error:{name}"


def save_record(record: dict, results_dir: str, json_path: Optional[str],
                secrets: list[str]) -> Optional[str]:
    """Persist a sanitized record atomically. Returns the path written, or None."""
    text = json.dumps(record, indent=2)
    text = redact(text, secrets)
    record = json.loads(text)
    if json_path:
        return atomic_write_json(json_path, record)
    directory = Path(results_dir)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = directory / f"smoke-{record.get('component', 'unknown')}-{stamp}.json"
    return atomic_write_json(path, record)


def print_preflight_banner(config: SmokeConfig, base_url: str, model: str,
                           messages: list[str], ok: bool) -> None:
    print(f"Airlock smoke preflight: {config.component}")
    print(f"  Purpose: {config.description}")
    for message in messages:
        print(f"  - {message}")
    if ok:
        print("  Preflight OK. A live test would send the smallest practical synthetic "
              f"request to {mask_url_credentials(base_url)} for model `{model}`.")
        print("  No request was sent. Re-run with --live --allow-billable to opt in.")
    else:
        print("  Preflight FAILED: resolve the items above before any live test. No request sent.")
