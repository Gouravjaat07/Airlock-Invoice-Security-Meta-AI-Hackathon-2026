"""Phase 3 provider live smoke (bounded, explicit opt-in only).

Default: preflight every provider (configuration only, NO network).
Live (--live --allow-billable): at most --max-calls synthetic
micro-requests total (default 3), one attempt each, no retries, tiny
synthetic inputs only. Never sends real invoices, bank data, or PINs.

Bounded budget: calls stop when --max-calls is exhausted; remaining
providers are reported NOT_TESTED (budget-exhausted), never PASS.

Request shapes follow the contracts verified 2026-11-01
(docs/phase3/CAPABILITY_MATRIX.md): Responses API for Meta (Spark,
SAM), file-transcription multipart for Voice, OpenAI-compatible chat
for Baseten and Glimmer.

Usage:
  python scripts/smoke_phase3.py [--provider all|meta-spark|meta-voice|meta-sam|baseten|glimmer]
  python scripts/smoke_phase3.py --live --allow-billable [--max-calls 3]
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import struct
import sys
import time
import urllib.error
import urllib.request
import zlib
from pathlib import Path
from typing import Callable, Mapping, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _smoke_common import (  # noqa: E402
    SmokeConfig,
    SmokeRequestError,
    add_common_args,
    classify_error,
    clamp_timeout,
    live_flag_misuse,
    live_requested_and_confirmed,
    mask_url_credentials,
    post_json,
    preflight,
    print_preflight_banner,
    redact,
    save_record,
    utc_now_iso,
)

CONTRIBUTOR_MODEL = "muse-spark-1.3-contributor"
MAX_CALLS_CAP = 10
SSE_LINE_CAP = 20000
SSE_BYTE_CAP = 2 * 1024 * 1024

CONFIGS = {
    "meta-spark": SmokeConfig(
        component="meta-spark", key_var="MODEL_API_KEY",
        base_url_default="https://api.meta.ai/v1",
        model_default="muse-spark-1.3",
        description="Minimal synthetic Responses text round-trip."),
    "meta-voice": SmokeConfig(
        component="meta-voice", key_var="MODEL_API_KEY",
        base_url_default="https://api.meta.ai/v1",
        model_default="muse-voice-transcribe-1.0",
        description="Synthetic 0.25s silence transcription (file mode)."),
    "meta-sam": SmokeConfig(
        component="meta-sam", key_var="MODEL_API_KEY",
        base_url_default="https://api.meta.ai/v1",
        model_default="sam-3.1",
        description="Synthetic 8x8 image concept segmentation (streamed)."),
    "baseten": SmokeConfig(
        component="baseten", key_var="BASETEN_API_KEY",
        base_url_default="https://inference.baseten.co/v1",
        model_default="meta-models/muse-spark-open-1026",
        description="Minimal synthetic chat round-trip (Spark Open)."),
    "glimmer": SmokeConfig(
        component="glimmer", key_var="GLIMMER_API_KEY",
        base_url_default="http://127.0.0.1:8081/v1",
        model_default="muse-glimmer",
        description="Local runtime /models probe + minimal chat round-trip."),
}

MODEL_VARS = {"meta-spark": "SPARK_MODEL", "meta-voice": "VOICE_MODEL",
              "meta-sam": "SAM_MODEL",
              "baseten": "BASETEN_SPARK_OPEN_MODEL",
              "glimmer": "GLIMMER_MODEL"}
BASE_VARS = {"meta-spark": "META_API_BASE", "meta-voice": "META_API_BASE",
             "meta-sam": "META_API_BASE", "baseten": "BASETEN_BASE_URL",
             "glimmer": "GLIMMER_BASE_URL"}


def _png_8x8() -> bytes:
    raw = b"\x00" + b"\x80\x80\x80" * 8
    pixels = raw * 8
    ihdr = struct.pack(">IIBBBBB", 8, 8, 8, 2, 0, 0, 0)
    idat = zlib.compress(pixels)
    out = b"\x89PNG\r\n\x1a\n"
    for kind, data in ((b"IHDR", ihdr), (b"IDAT", idat)):
        out += struct.pack(">I", len(data)) + kind + data
        out += struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    out += struct.pack(">I", 0) + b"IEND"
    out += struct.pack(">I", zlib.crc32(b"IEND") & 0xFFFFFFFF)
    return out


def _wav_silence() -> bytes:
    frames = 4000  # 0.25 s at 16 kHz
    data = b"\x00" * (frames * 2)
    fmt = struct.pack("<HHIIHH", 1, 1, 16000, 32000, 2, 16)
    chunks = struct.pack("<4sI", b"fmt ", 16) + fmt
    chunks += struct.pack("<4sI", b"data", len(data)) + data
    return b"RIFF" + struct.pack("<I", 4 + len(chunks)) + b"WAVE" + chunks


def _post_sse(url: str, payload: dict, api_key: str,
              timeout: int) -> tuple[str, int]:
    """POST an SSE request; return (raw_text, latency_ms). Bounded."""
    body = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json",
               "Accept": "text/event-stream",
               "Authorization": "Bearer " + api_key}
    request = urllib.request.Request(url, data=body, headers=headers,
                                     method="POST")
    start = time.perf_counter()
    chunks: list[bytes] = []
    total = 0
    lines = 0
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise SmokeHttpError(response.status,
                                 response.read(4096).decode("utf-8", "replace"))
        for raw_line in response:
            lines += 1
            total += len(raw_line)
            if lines > SSE_LINE_CAP or total > SSE_BYTE_CAP:
                raise SmokeHttpError(None, "stream exceeded smoke bounds")
            chunks.append(raw_line)
    latency = int((time.perf_counter() - start) * 1000)
    return b"".join(chunks).decode("utf-8", "replace"), latency


class SmokeHttpError(Exception):
    def __init__(self, http_status: Optional[int], message: str) -> None:
        super().__init__(message)
        self.http_status = http_status


def _post_multipart(url: str, fields: dict[str, str],
                    file_field: str, filename: str, file_bytes: bytes,
                    mime: str, api_key: str, timeout: int
                    ) -> tuple[Optional[int], str, int]:
    boundary = "----airlocksmoke7d8f"
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; "
            f'name="{name}"\r\n\r\n{value}\r\n'.encode())
    parts.append(
        f"--{boundary}\r\nContent-Disposition: form-data; "
        f'name="{file_field}"; filename="{filename}"\r\n'
        f"Content-Type: {mime}\r\n\r\n".encode() + file_bytes + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(parts)
    headers = {"Content-Type": f"multipart/form-data; boundary={boundary}",
               "Accept": "application/json",
               "Authorization": "Bearer " + api_key}
    request = urllib.request.Request(url, data=body, headers=headers,
                                     method="POST")
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            text = response.read().decode("utf-8", "replace")
            status = response.status
    except urllib.error.HTTPError as exc:  # type: ignore[attr-defined]
        text = exc.read().decode("utf-8", "replace")
        status = exc.code
    latency = int((time.perf_counter() - start) * 1000)
    return status, text, latency


def _live_spark_text(base_url: str, model: str, api_key: str,
                     timeout: int) -> tuple[bool, str, Optional[int], int]:
    payload = {
    "model": model,
    "input": "Reply with exactly: AIRLOCK_SMOKE_OK",
    "store": False,
    "reasoning": {
        "effort": "minimal"
    },
    "max_output_tokens": 256,
}
    try:
        status, body, latency = post_json(
            f"{base_url.rstrip('/')}/responses", payload, api_key, timeout)
    except SmokeRequestError as exc:
        return False, f"HTTP {exc.http_status}", exc.http_status, \
            exc.latency_ms or 0
    try:
        data = json.loads(body)
        if data.get("status") != "completed":
            details = data.get("incomplete_details") or {}
            reason = details.get("reason") or "unknown"
            return False, f"response incomplete: {reason}", status, latency
        items = data.get("output", [])
        texts = [part.get("text", "")
                 for item in items if isinstance(item, dict)
                 for part in (item.get("content", []) or [])
                 if isinstance(part, dict)]
    except (ValueError, AttributeError):
        return False, "invalid JSON", status, latency
    ok = any("AIRLOCK_SMOKE_OK" in text for text in texts)
    return ok, ("marker echoed" if ok else "marker missing"), status, latency


def _live_voice(base_url: str, model: str, api_key: str,
                timeout: int) -> tuple[bool, str, Optional[int], int]:
    fields = {"request": json.dumps({"mode": "PUSH_TO_TALK", "model": model,
                                     "audioEncoding": "WAV"})}
    status, body, latency = _post_multipart(
        f"{base_url.rstrip('/')}/asr/transcribe?sessionId=airlock-smoke",
        fields, "audio", "smoke.wav", _wav_silence(), "audio/wav",
        api_key, timeout)
    if status != 200:
        return False, f"HTTP {status}", status, latency
    try:
        data = json.loads(body)
    except ValueError:
        return False, "invalid JSON", status, latency
    ok = isinstance(data, dict) and isinstance(data.get("transcript"), str)
    return ok, ("transcript returned" if ok else "no transcript"), status, latency


def _live_sam(base_url: str, model: str, api_key: str,
              timeout: int) -> tuple[bool, str, Optional[int], int]:
    encoded = base64.b64encode(_png_8x8()).decode("ascii")
    payload = {"model": model,
               "input": [{"type": "message", "role": "user", "content": [
                   {"type": "input_text", "text": "square"},
                   {"type": "input_image",
                    "image_url": f"data:image/png;base64,{encoded}"}]}],
               "store": False, "stream": True}
    try:
        text, latency = _post_sse(f"{base_url.rstrip('/')}/responses",
                                  payload, api_key, timeout)
    except SmokeHttpError as exc:
        return False, str(exc)[:200], exc.http_status, 0
    completed = "response.completed" in text
    failed = "response.failed" in text
    if completed and not failed:
        return True, "stream completed (empty lane = zero matches ok)", 200, latency
    return False, "stream did not complete", None, latency


def _live_chat(base_url: str, model: str, api_key: str, timeout: int
               ) -> tuple[bool, str, Optional[int], int]:
    payload: dict = {"model": model,
                     "messages": [{"role": "user", "content":
                                   "Reply with exactly: AIRLOCK_SMOKE_OK"}],
                     "max_tokens": 16}
    # Muse Spark Open is reasoning-capable: budget output tokens for
    # internal reasoning plus the short visible marker. Baseten's
    # OpenAI-compatible endpoint documents top-level `reasoning_effort`
    # (enum incl. "low") and `max_tokens`, so both are safe to send
    # here. Model-specific: Glimmer's request contract stays unchanged.
    if "muse-spark-open" in model.lower():
        payload["max_tokens"] = 512
        payload["reasoning_effort"] = "low"
    if api_key:
        try:
            status, body, latency = post_json(
                f"{base_url.rstrip('/')}/chat/completions", payload,
                api_key, timeout)
        except SmokeRequestError as exc:
            if exc.http_status is None:
                # Transport failure (timeout/refused/reset): no HTTP
                # status exists, so report the cause, never "HTTP None".
                return False, f"request failed: {exc}"[:200], None, \
                    exc.latency_ms or 0
            return False, f"HTTP {exc.http_status}", exc.http_status, \
                exc.latency_ms or 0
    else:
        # Keyless local runtime: same shape, no Authorization header.
        raw = json.dumps(payload).encode()
        request = urllib.request.Request(
            f"{base_url.rstrip('/')}/chat/completions", data=raw,
            headers={"Content-Type": "application/json"}, method="POST")
        start = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read().decode("utf-8", "replace")
                status: Optional[int] = response.status
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            status = exc.code
        latency = int((time.perf_counter() - start) * 1000)
    if status != 200:
        return False, f"HTTP {status}", status, latency
    try:
        data = json.loads(body)
    except ValueError:
        return False, "invalid JSON", status, latency
    try:
        choice = data["choices"][0]
        content = choice["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return False, "invalid chat shape", status, latency
    finish = choice.get("finish_reason") if isinstance(choice, dict) else None
    if finish == "length":
        return False, "incomplete response (finish_reason=length)", \
            status, latency
    if not isinstance(content, str) or not content:
        return False, "empty response content", status, latency
    # The exact marker in the visible response is the only PASS signal:
    # HTTP 200 alone never counts as successful inference.
    ok = "AIRLOCK_SMOKE_OK" in content
    return ok, ("marker echoed" if ok else "marker missing"), status, latency


LIVE_RUNNERS: dict[str, Callable] = {
    "meta-spark": _live_spark_text,
    "meta-voice": _live_voice,
    "meta-sam": _live_sam,
    "baseten": _live_chat,
    "glimmer": _live_chat,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Phase 3 provider live smoke.")
    add_common_args(parser)
    # Phase 3 evidence belongs under results/phase3 — never in the
    # Phase 1 directory (the shared default exists for Phase 1
    # scripts, whose records phase1_check.py inventories).
    parser.set_defaults(results_dir="results/phase3")
    parser.add_argument("--provider", default="all",
                        choices=["all", *CONFIGS.keys()])
    parser.add_argument("--max-calls", type=int, default=3)
    return parser


def _resolve(name: str, env: Mapping[str, str]) -> tuple[str, str, str]:
    base = (env.get(BASE_VARS[name]) or "").strip() or \
        CONFIGS[name].base_url_default
    model = (env.get(MODEL_VARS[name]) or "").strip() or \
        CONFIGS[name].model_default
    key = (env.get(CONFIGS[name].key_var) or "").strip()
    return base, model, key


def main(argv: Optional[list[str]] = None,
         env: Optional[Mapping[str, str]] = None,
         live_runner: Optional[Callable] = None) -> int:
    """Entry point. `live_runner` is a test double for the live call.

    Double signature: (name, base, model, key, timeout) ->
    (passed, note, http_status, latency_ms). Production calls pass None.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    env = env if env is not None else os.environ
    run_one = live_runner or (lambda name, base, model, key, timeout:
                              LIVE_RUNNERS[name](base, model, key, timeout))
    selected = list(CONFIGS) if args.provider == "all" else [args.provider]
    budget = max(1, min(int(args.max_calls), MAX_CALLS_CAP))

    misuse = live_flag_misuse(args)
    if misuse:
        print(f"ERROR: {misuse}", file=sys.stderr)
        return 2
    if args.base_url:
        print("ERROR: base URLs are env-driven; set META_API_BASE/"
              "BASETEN_BASE_URL/GLIMMER_BASE_URL instead of --base-url.",
              file=sys.stderr)
        return 2
    if args.model and args.provider == "all":
        print("ERROR: --model applies to a single provider only; pass "
              "--provider <name> with --model, or set the model via "
              "SPARK_MODEL/VOICE_MODEL/SAM_MODEL/BASETEN_SPARK_OPEN_MODEL/"
              "GLIMMER_MODEL.", file=sys.stderr)
        return 2
    live = live_requested_and_confirmed(args)
    timeout = clamp_timeout(args.timeout)
    secrets: list[str] = []
    entries: list[dict] = []
    calls_used = 0

    for name in selected:
        base, model, key = _resolve(name, env)
        if args.model:
            # Single-provider runs only (rejected with --provider all
            # above): explicit CLI override wins over env/default.
            model = args.model.strip() or model
        if key:
            secrets.append(key)
        if name == "glimmer" and not key:
            key_note = "key unset (local runtimes often need none)"
        else:
            key_note = None
        ok, messages = preflight(CONFIGS[name], base, model, env)
        if name == "glimmer" and not key:
            # Local runtimes may be keyless: reachability decides live.
            ok = True
            messages = [message for message in messages
                        if "GLIMMER_API_KEY is unset" not in message]
            messages.append(key_note or "")
        if model == CONTRIBUTOR_MODEL or model.endswith("-contributor"):
            ok = False
            messages.append("Refusing: contributor models must never receive "
                            "Airlock runtime data.")
        print_preflight_banner(CONFIGS[name], base, model, messages, ok)
        entry: dict = {"provider": name, "model_id": model,
                       "endpoint": mask_url_credentials(base),
                       "timestamp_utc": utc_now_iso(),
                       "preflight_ok": ok, "status": "NOT_TESTED",
                       "http_status": None, "latency_ms": None,
                       "error_category": None, "notes": ""}
        if not live:
            entry["notes"] = ("Preflight only: no live request sent. "
                              "Re-run with --live --allow-billable.")
            entries.append(entry)
            continue
        if not ok:
            entry["notes"] = "Preflight failed; no live request sent."
            entries.append(entry)
            continue
        if calls_used >= budget:
            entry["notes"] = ("Budget exhausted "
                              f"({budget} calls); not attempted.")
            entries.append(entry)
            continue
        print(f"  Live mode confirmed: one synthetic micro-request "
              f"(timeout {timeout}s, no retries)...")
        calls_used += 1
        try:
            passed, note, http_status, latency = run_one(
                name, base, model, key, timeout)
        except Exception as exc:  # noqa: BLE001 - classify, never leak
            entry.update({"status": "FAIL", "http_status": None,
                          "latency_ms": None,
                          "error_category": classify_error(exc),
                          "notes": redact(str(exc), secrets)[:300]})
            entries.append(entry)
            continue
        entry.update({"status": "PASS" if passed else "FAIL",
                      "http_status": http_status, "latency_ms": latency,
                      "error_category": None if passed else "round-trip-failed",
                      "notes": note})
        entries.append(entry)
        print(f"  Live result: {entry['status']} (http={http_status}, "
              f"latency_ms={latency}) — {note}")

    record = {"component": "phase3-smoke", "test_type": "live-smoke" if live
              else "preflight", "timestamp_utc": utc_now_iso(),
              "budget": budget, "calls_used": calls_used,
              "providers": entries}
    saved = save_record(record, args.results_dir, args.json_path, secrets)
    print(f"  Sanitized record saved to {saved}")
    if not live:
        print("Preflight only: no live request sent.")
        return 0
    statuses = {entry["status"] for entry in entries}
    if statuses <= {"PASS"}:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
