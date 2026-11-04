"""offload_sync: loop-free path runs inline without suspension.

Drives the coroutine exactly like the ASGI harness does (`send(None)`
once): without a running loop the work must complete inline and never
suspend on an `asyncio` awaitable. The worker-thread path only engages
under a real server (uvicorn) and is covered by operational checks.
"""

from __future__ import annotations

import pytest

from app.api.cases import offload_sync


def test_offload_runs_inline_without_loop():
    coro = offload_sync(lambda: "ok")
    try:
        coro.send(None)
    except StopIteration as done:
        assert done.value == "ok"
    else:
        coro.close()
        raise AssertionError("offload_sync suspended without a loop")


def test_offload_propagates_errors_inline():
    def _boom():
        raise ValueError("nope")

    coro = offload_sync(_boom)
    with pytest.raises(ValueError, match="nope"):
        coro.send(None)
