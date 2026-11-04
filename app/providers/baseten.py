"""Muse Spark Open invoice reader (Baseten, OpenAI-compatible).

Separate provider adapter (NOT a Meta client with a different token):
chat/completions against the configured Baseten base URL. Image input
only — the chat protocol has no PDF file part, so PDFs are refused
explicitly rather than misrouted. The call itself runs through the
shared chat-protocol core (`app.providers.chat`).
"""

from __future__ import annotations

import httpx

from app.adapters.readers import ReaderResult
from app.config import Settings
from app.providers.chat import read_chat_extraction
from app.providers.types import ProviderName

ADAPTER_ID = "baseten-spark-open"
ADAPTER_VERSION = "3.0.0"


class BasetenSparkReader:
    """Invoice extraction via hosted Muse Spark Open."""

    adapter_id = ADAPTER_ID
    adapter_version = ADAPTER_VERSION

    def __init__(self, settings: Settings, *,
                 transport: httpx.BaseTransport | None = None) -> None:
        self.settings = settings
        self._transport = transport

    def read(self, artifact_bytes: bytes) -> ReaderResult:
        settings = self.settings
        return read_chat_extraction(
            adapter_label="Spark Open reader", log_name="baseten",
            provider=ProviderName.BASETEN,
            model=settings.baseten_spark_open_model,
            base_url=settings.baseten_base_url,
            credential=settings.baseten_api_key,
            pool_key=f"baseten:{settings.extraction_timeout_s}",
            settings=settings, artifact_bytes=artifact_bytes,
            transport=self._transport)
