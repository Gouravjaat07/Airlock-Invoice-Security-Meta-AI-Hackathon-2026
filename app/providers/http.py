"""Shared synchronous provider HTTP core (httpx, pooled, bounded).

One synchronous client per provider: the ASGI test harness forbids
loop-bound awaits, so provider I/O is blocking and isolated behind the
existing semaphore pattern instead of an async framework. TLS
verification is never disabled; headers and bodies are never logged.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Iterator

import httpx

from app.core.logging import get_logger
from app.providers.types import (
    ProviderError,
    ProviderErrorCategory,
    ProviderName,
)

logger = get_logger("airlock.providers.http")

MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_SSE_EVENTS = 100_000
USER_AGENT = "airlock-phase3/1.0"


def _parse_json_bytes(raw: bytes) -> Any:
    """Best-effort JSON decode of a bounded body; None when empty/invalid."""
    if not raw.strip():
        return None
    try:
        return httpx.Response(200, content=raw).json()
    except ValueError:
        return None


def _timeout_error(exc: httpx.TimeoutException,
                   provider: ProviderName) -> ProviderError:
    """Split timeouts by ambiguity: connect/pool never reached the server
    (safe to retry); read/write timeouts may have been accepted and billed
    (reconciliation state, never auto-retried)."""
    if isinstance(exc, (httpx.ConnectTimeout, httpx.PoolTimeout)):
        return ProviderError(ProviderErrorCategory.TIMEOUT,
                             "Provider connection timed out",
                             provider=provider)
    return ProviderError(
        ProviderErrorCategory.INCOMPLETE,
        "Provider response interrupted; the request may already have "
        "been accepted",
        provider=provider)


def parse_retry_after(headers: httpx.Headers | dict[str, str]) -> float | None:
    """Parse `Retry-After` (delay seconds or HTTP date); None when absent."""
    raw: str | None = None
    if isinstance(headers, httpx.Headers):
        raw = headers.get("retry-after")
    else:
        for key, value in headers.items():
            if key.lower() == "retry-after":
                raw = value
                break
    if raw is None:
        return None
    raw = raw.strip()
    if not raw:
        return None
    try:
        delay = float(raw)
    except ValueError:
        try:
            moment = parsedate_to_datetime(raw)
        except (TypeError, ValueError):
            return None
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        delay = (moment - datetime.now(timezone.utc)).total_seconds()
    if delay != delay:  # NaN
        return None
    return max(0.0, min(delay, 300.0))


class HttpClient:
    """Pooled sync client for one provider base URL."""

    def __init__(self, *, provider: ProviderName, base_url: str,
                 credential: str | None, connect_timeout_s: float,
                 read_timeout_s: float,
                 transport: httpx.BaseTransport | None = None) -> None:
        self.provider = provider
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            transport=transport,
            timeout=httpx.Timeout(connect=connect_timeout_s,
                                  read=read_timeout_s,
                                  write=read_timeout_s,
                                  pool=connect_timeout_s),
            verify=True,  # TLS validation is never disabled
            headers={"User-Agent": USER_AGENT},
        )
        self._credential = credential

    def close(self) -> None:
        self._client.close()

    def _headers(self, operation_id: str) -> dict[str, str]:
        headers = {"X-Request-ID": operation_id}
        if self._credential:
            headers["Authorization"] = "Bearer " + self._credential
        return headers

    def _bounded_body(self, response: httpx.Response) -> bytes:
        # Callers always pass a streaming response, so the cap trips
        # while bytes are still arriving (no unbounded pre-buffer).
        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_bytes(chunk_size=65536):
            total += len(chunk)
            if total > MAX_RESPONSE_BYTES:
                raise ProviderError(
                    ProviderErrorCategory.MALFORMED,
                    "Provider response exceeded size limit",
                    provider=self.provider)
            chunks.append(chunk)
        return b"".join(chunks)

    def post_json(self, path: str, payload: dict[str, Any], *,
                  operation_id: str) -> tuple[int, httpx.Headers, Any]:
        """POST JSON; returns (status, headers, parsed body or None).

        The body is read through the size cap while streaming, so an
        oversized response fails before it is fully buffered. Transport
        failures raise ProviderError(TIMEOUT/INCOMPLETE/UNAVAILABLE).
        HTTP error statuses are returned for the caller to map.
        """
        try:
            with self._client.stream("POST", path, json=payload,
                                     headers=self._headers(operation_id)
                                     ) as response:
                status = response.status_code
                headers = response.headers
                raw = self._bounded_body(response)
        except httpx.TimeoutException as exc:
            raise _timeout_error(exc, self.provider) from exc
        except httpx.TransportError as exc:
            raise ProviderError(ProviderErrorCategory.UNAVAILABLE,
                                "Provider unreachable",
                                provider=self.provider) from exc
        parsed = _parse_json_bytes(raw)
        logger.info("provider http status=%s path=%s op=%s bytes=%d",
                    status, path, operation_id, len(raw))
        return status, headers, parsed

    def get_json(self, path: str, *,
                 operation_id: str) -> tuple[int, Any]:
        """GET + bounded JSON body (operator probes); never raises on
        status — callers map non-200 themselves. Transport failures raise
        ProviderError like `post_json`."""
        try:
            with self._client.stream("GET", path,
                                     headers=self._headers(operation_id)
                                     ) as response:
                status = response.status_code
                raw = self._bounded_body(response)
        except httpx.TimeoutException as exc:
            raise _timeout_error(exc, self.provider) from exc
        except httpx.TransportError as exc:
            raise ProviderError(ProviderErrorCategory.UNAVAILABLE,
                                "Provider unreachable",
                                provider=self.provider) from exc
        parsed = _parse_json_bytes(raw)
        logger.info("provider get status=%s path=%s op=%s bytes=%d",
                    status, path, operation_id, len(raw))
        return status, parsed

    def post_multipart(self, path: str, *, data: dict[str, str],
                       files: dict[str, tuple[str, bytes, str]],
                       operation_id: str,
                       extra_headers: dict[str, str] | None = None,
                       ) -> tuple[int, httpx.Headers, Any]:
        """POST multipart (file upload); same contract as `post_json`."""
        headers = self._headers(operation_id)
        if extra_headers:
            headers.update(extra_headers)
        try:
            with self._client.stream("POST", path, data=data, files=files,
                                     headers=headers) as response:
                status = response.status_code
                resp_headers = response.headers
                raw = self._bounded_body(response)
        except httpx.TimeoutException as exc:
            raise _timeout_error(exc, self.provider) from exc
        except httpx.TransportError as exc:
            raise ProviderError(ProviderErrorCategory.UNAVAILABLE,
                                "Provider unreachable",
                                provider=self.provider) from exc
        parsed = _parse_json_bytes(raw)
        logger.info("provider upload status=%s path=%s op=%s bytes=%d",
                    status, path, operation_id, len(raw))
        return status, resp_headers, parsed

    def stream_sse(self, path: str, payload: dict[str, Any], *,
                   operation_id: str) -> Iterator[tuple[str | None, str]]:
        """POST + yield `(event, data)` SSE pairs with byte/event caps."""
        headers = self._headers(operation_id)
        headers["Accept"] = "text/event-stream"
        try:
            with self._client.stream("POST", path, json=payload,
                                     headers=headers) as response:
                if response.status_code != 200:
                    raw = self._bounded_body(response)
                    raise _HttpStatusSignal(response.status_code,
                                             response.headers, raw[:65536])
                yield from _iter_sse(response, self.provider, operation_id)
        except _HttpStatusSignal:
            raise
        except httpx.TimeoutException as exc:
            raise _timeout_error(exc, self.provider) from exc
        except httpx.TransportError as exc:
            raise ProviderError(ProviderErrorCategory.UNAVAILABLE,
                                "Provider stream interrupted",
                                provider=self.provider) from exc


class _HttpStatusSignal(Exception):
    """Non-200 on an SSE request: status + headers + truncated body."""

    def __init__(self, status: int, headers: httpx.Headers, body: bytes) -> None:
        super().__init__(f"HTTP {status}")
        self.status = status
        self.headers = headers
        self.body = body


def _iter_sse(response: httpx.Response, provider: ProviderName,
              operation_id: str) -> Iterator[tuple[str | None, str]]:
    total = 0
    events = 0
    event_name: str | None = None
    data_lines: list[str] = []

    def _flush() -> tuple[str | None, str] | None:
        nonlocal event_name, data_lines
        if event_name is None and not data_lines:
            return None
        out = (event_name, "\n".join(data_lines))
        event_name = None
        data_lines = []
        return out

    for raw_line in response.iter_lines():
        total += len(raw_line) + 1
        if total > MAX_RESPONSE_BYTES:
            raise ProviderError(ProviderErrorCategory.MALFORMED,
                                "Provider stream exceeded size limit",
                                provider=provider)
        line = raw_line.strip()
        if not line:
            flushed = _flush()
            if flushed is not None:
                events += 1
                if events > MAX_SSE_EVENTS:
                    raise ProviderError(ProviderErrorCategory.MALFORMED,
                                        "Provider stream exceeded event limit",
                                        provider=provider)
                yield flushed
            continue
        if line.startswith(":"):
            continue  # comment / heartbeat
        if line.startswith("event:"):
            event_name = line[6:].strip() or None
        elif line.startswith("data:"):
            data_lines.append(line[5:].strip())
    flushed = _flush()
    if flushed is not None:
        yield flushed
    logger.info("provider sse complete op=%s events=%d bytes=%d",
                operation_id, events, total)


class ClientPool:
    """Process-lifetime pooled clients, one per provider key.

    Tests pass an explicit transport and bypass the cache (fresh client
    per call, closed by the caller). `close_all` runs on app shutdown.

    Pool keys pin one base URL, credential, and timeout set for the
    process lifetime: provider endpoint configuration is assumed static
    after startup (a config change requires a restart to take effect).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._clients: dict[str, HttpClient] = {}
        self._test_transports: dict[str, httpx.BaseTransport] = {}

    def set_test_transport(self, key: str,
                           transport: httpx.BaseTransport) -> None:
        """Route one pool key through a stub transport (tests only)."""
        with self._lock:
            self._test_transports[key] = transport

    def clear_test_transports(self) -> None:
        with self._lock:
            self._test_transports = {}

    def get(self, key: str, *, provider: ProviderName, base_url: str,
            credential: str | None, connect_timeout_s: float,
            read_timeout_s: float,
            transport: httpx.BaseTransport | None = None) -> HttpClient:
        if transport is None:
            with self._lock:
                transport = self._test_transports.get(key)
        if transport is not None:
            return HttpClient(provider=provider, base_url=base_url,
                              credential=credential,
                              connect_timeout_s=connect_timeout_s,
                              read_timeout_s=read_timeout_s,
                              transport=transport)
        with self._lock:
            client = self._clients.get(key)
            if client is None:
                client = HttpClient(provider=provider, base_url=base_url,
                                    credential=credential,
                                    connect_timeout_s=connect_timeout_s,
                                    read_timeout_s=read_timeout_s)
                self._clients[key] = client
            return client

    def close_all(self) -> None:
        with self._lock:
            clients, self._clients = list(self._clients.values()), {}
        for client in clients:
            try:
                client.close()
            except Exception:  # noqa: BLE001 - shutdown best effort
                logger.warning("provider client close failed")


POOL = ClientPool()
