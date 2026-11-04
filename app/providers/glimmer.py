"""Muse Glimmer invoice reader (optional local OpenAI-compatible runtime).

The local endpoint is never assumed: every call is a normal guarded
request (connect failures surface as UNAVAILABLE), and `preflight`
offers an explicit availability probe for operators and smoke tests.
Image input only (same chat-protocol limitation as Baseten); no model
downloads, no weight management, no GPU assumptions in code. The call
itself runs through the shared chat-protocol core
(`app.providers.chat`).
"""

from __future__ import annotations

from typing import Any

import httpx

from app.adapters.readers import ReaderResult
from app.config import Settings
from app.core.ids import new_id
from app.providers.chat import chat_client, read_chat_extraction
from app.providers.types import ProviderError, ProviderName

ADAPTER_ID = "glimmer-local"
ADAPTER_VERSION = "3.0.0"


def preflight(settings: Settings, *,
              transport: httpx.BaseTransport | None = None) -> dict[str, Any]:
    """Probe the local runtime (`GET /models`); never raises, reports state.

    Returns {"available": bool, "models": [...], "reason": str}.
    A passing preflight proves reachability only, not inference quality.
    """
    client = chat_client(
        pool_key=f"glimmer-preflight:{settings.provider_connect_timeout_s}",
        provider=ProviderName.GLIMMER, base_url=settings.glimmer_base_url,
        credential=settings.glimmer_api_key,
        connect_timeout_s=settings.provider_connect_timeout_s,
        read_timeout_s=settings.provider_connect_timeout_s,
        transport=transport)
    try:
        status, body = client.get_json("/models",
                                       operation_id=new_id("op"))
    except ProviderError as exc:
        if transport is not None:
            client.close()
        return {"available": False, "models": [],
                "reason": f"unreachable: {exc.category.value}"}
    except Exception as exc:  # noqa: BLE001 - probe reports, never raises
        if transport is not None:
            client.close()
        return {"available": False, "models": [],
                "reason": f"unreachable: {type(exc).__name__}"}
    if transport is not None:
        client.close()
    if status != 200:
        return {"available": False, "models": [],
                "reason": f"local runtime returned HTTP {status}"}
    if not isinstance(body, dict):
        return {"available": False, "models": [],
                "reason": "local runtime returned invalid JSON"}
    models: list[str] = []
    if isinstance(body.get("data"), list):
        for entry in body["data"]:
            if isinstance(entry, dict) and isinstance(entry.get("id"), str):
                models.append(entry["id"])
    if settings.glimmer_model not in models:
        return {"available": False, "models": models,
                "reason": f"model {settings.glimmer_model!r} not served"}
    return {"available": True, "models": models, "reason": "ok"}


class GlimmerReader:
    """Invoice extraction via the local Glimmer-compatible runtime."""

    adapter_id = ADAPTER_ID
    adapter_version = ADAPTER_VERSION

    def __init__(self, settings: Settings, *,
                 transport: httpx.BaseTransport | None = None) -> None:
        self.settings = settings
        self._transport = transport

    def read(self, artifact_bytes: bytes) -> ReaderResult:
        settings = self.settings
        return read_chat_extraction(
            adapter_label="Glimmer reader", log_name="glimmer",
            provider=ProviderName.GLIMMER, model=settings.glimmer_model,
            base_url=settings.glimmer_base_url,
            credential=settings.glimmer_api_key,
            pool_key=f"glimmer:{settings.extraction_timeout_s}",
            settings=settings, artifact_bytes=artifact_bytes,
            transport=self._transport)
