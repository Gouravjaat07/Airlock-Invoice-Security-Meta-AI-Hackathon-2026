"""Minimal socket-free ASGI test client (stdlib asyncio only).

Rationale: this sandbox forbids `listen()`, which Starlette's TestClient
portal needs on Windows. This harness drives the real FastAPI app
in-process (routing, dependencies, error handlers) without sockets,
threads, or extra packages. Each request runs on a fresh event loop; the
app holds no loop-bound state.

Limitations vs a socket client: no real HTTP parsing, single Set-Cookie
header per response, no streaming. Anything beyond that needs an
unsandboxed `uvicorn` run (see docs/phase2/LIMITATIONS.md).
"""

from __future__ import annotations

import io
import json as _json
import secrets
from typing import Any
from urllib.parse import urlsplit


def _run(coro):
    """Drive a coroutine to completion with no event loop at all.

    The app awaits only plain coroutines (routing, validation, sqlite,
    spooled uploads), so one `send(None)` runs the whole chain. Anything
    awaiting a real Future/lock/sleep suspends instead of returning and
    fails loudly here -- the app must stay loop-free for this harness.
    """
    try:
        coro.send(None)
    except StopIteration as done:
        return done.value
    raise AssertionError(
        "ASGI coroutine suspended on a loop-bound awaitable; "
        "the app must not use asyncio primitives (sandbox has no sockets)")


class Response:
    def __init__(self, status: int, headers: list[tuple[bytes, bytes]],
                 body: bytes):
        self.status_code = status
        self.headers: dict[str, str] = {}
        for key, value in headers:
            name = key.decode("latin-1").lower()
            text = value.decode("latin-1")
            if name == "set-cookie" and name in self.headers:
                self.headers[name] += "\n" + text
            else:
                self.headers[name] = text
        self._body = body

    @property
    def text(self) -> str:
        return self._body.decode("utf-8", errors="replace")

    @property
    def content(self) -> bytes:
        return self._body

    def json(self) -> Any:
        return _json.loads(self.text)


def encode_multipart(files: list[tuple[str, tuple[str, bytes, str]]],
                     boundary: str) -> bytes:
    buf = io.BytesIO()
    for field_name, (filename, data, content_type) in files:
        buf.write(f"--{boundary}\r\n".encode())
        buf.write(f'Content-Disposition: form-data; name="{field_name}"; '
                  f'filename="{filename}"\r\n'.encode())
        buf.write(f"Content-Type: {content_type}\r\n\r\n".encode())
        buf.write(data)
        buf.write(b"\r\n")
    buf.write(f"--{boundary}--\r\n".encode())
    return buf.getvalue()


class ASGIClient:
    """Sync test client for an ASGI app with cookie + header persistence."""

    def __init__(self, app):
        self.app = app
        self.cookies: dict[str, str] = {}
        self.headers: dict[str, str] = {}
        self.base_url = "http://testserver"

    # -- cookie jar -----------------------------------------------------
    def _store_cookies(self, response: Response) -> None:
        raw = response.headers.get("set-cookie", "")
        for line in raw.split("\n"):
            if not line.strip():
                continue
            pair = line.split(";", 1)[0]
            if "=" not in pair:
                continue
            name, _, value = pair.partition("=")
            name, value = name.strip(), value.strip().strip('"')
            if "expires=thu, 01 jan 1970" in line.lower() or \
                    "max-age=0" in line.lower().replace(" ", ""):
                self.cookies.pop(name, None)
            else:
                self.cookies[name] = value

    # -- requests -------------------------------------------------------
    def request(self, method: str, path: str, *,
                headers: dict[str, str] | None = None,
                json: Any = None,
                content: bytes | None = None,
                files: list | None = None) -> Response:
        if path.startswith("http"):
            split = urlsplit(path)
            path_only, query = split.path, split.query
        else:
            path_only, _, query = path.partition("?")
        body = content or b""
        request_headers = {k.lower(): v for k, v in self.headers.items()}
        request_headers.update({k.lower(): v
                                for k, v in (headers or {}).items()})
        if self.cookies:
            jar = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
            request_headers["cookie"] = jar
        if json is not None:
            body = _json.dumps(json).encode()
            request_headers["content-type"] = "application/json"
        if files is not None:
            boundary = "----airlock" + secrets.token_hex(8)
            body = encode_multipart(files, boundary)
            request_headers["content-type"] = \
                f"multipart/form-data; boundary={boundary}"
        scope = {
            "type": "http",
            "http_version": "1.1",
            "method": method.upper(),
            "scheme": "http",
            "path": path_only,
            "raw_path": path_only.encode(),
            "query_string": query.encode(),
            "headers": [(k.encode(), v.encode())
                        for k, v in request_headers.items()],
            "client": ("127.0.0.1", 50000),
            "server": ("testserver", 80),
        }
        return _run(self._exchange(scope, body))

    async def _exchange(self, scope: dict, body: bytes) -> Response:
        sent = False

        async def receive() -> dict:
            nonlocal sent
            if sent:
                return {"type": "http.disconnect"}
            sent = True
            return {"type": "http.request", "body": body,
                    "more_body": False}

        messages: list[dict] = []

        async def send(message: dict) -> None:
            messages.append(message)

        try:
            await self.app(scope, receive, send)
        except Exception as exc:  # pragma: no cover - harness guard
            raise AssertionError(f"ASGI app raised: {exc!r}") from exc
        status = 500
        headers: list[tuple[bytes, bytes]] = []
        chunks = []
        for message in messages:
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = list(message.get("headers", []))
            elif message["type"] == "http.response.body":
                chunks.append(message.get("body", b""))
        response = Response(status, headers, b"".join(chunks))
        self._store_cookies(response)
        return response

    def get(self, path: str, **kwargs) -> Response:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs) -> Response:
        return self.request("POST", path, **kwargs)

    def patch(self, path: str, **kwargs) -> Response:
        return self.request("PATCH", path, **kwargs)

    def put(self, path: str, **kwargs) -> Response:
        return self.request("PUT", path, **kwargs)

    def delete(self, path: str, **kwargs) -> Response:
        return self.request("DELETE", path, **kwargs)
