"""Shared provider-test fakes (offline, stub transports only).

Fake credentials are short inert markers (never secret-shaped, per
`check_secret_hygiene.py`). No helper performs network I/O.
"""

from __future__ import annotations

import httpx

from app.config import Settings

FAKE_KEY = "tk"


def provider_settings(**overrides) -> Settings:
    base = {
        "environment": "test",
        "model_api_key": FAKE_KEY,
        "baseten_api_key": FAKE_KEY,
        "reader_provider": "spark",
        "voice_provider": "meta",
        "vision_provider": "sam",
        "provider_max_retries": 0,
    }
    base.update(overrides)
    return Settings(**base)


def stub_transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def responses_ok(text: str, *, model: str = "muse-spark-1.3",
                 response_id: str = "resp_1",
                 usage: dict | None = None) -> dict:
    return {
        "id": response_id,
        "object": "response",
        "status": "completed",
        "model": model,
        "output": [{"id": "msg_1", "type": "message", "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": text,
                                 "annotations": []}]}],
        "usage": usage or {"input_tokens": 10, "output_tokens": 5,
                           "total_tokens": 15},
    }


def chat_ok(text: str, *, model: str = "meta-models/muse-spark-open-1026",
            finish: str = "stop") -> dict:
    return {
        "id": "chatcmpl_1",
        "object": "chat.completion",
        "model": model,
        "choices": [{"index": 0,
                     "message": {"role": "assistant", "content": text},
                     "finish_reason": finish}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5,
                  "total_tokens": 15},
    }


def error_envelope(message: str, *, type_: str = "server_error",
                   code: str | None = None) -> dict:
    err: dict = {"message": message, "type": type_}
    if code is not None:
        err["code"] = code
    return {"error": err}


def valid_extraction_json() -> str:
    import json
    return json.dumps({
        "vendor_name": "Acme Flour Mills",
        "invoice_number": "INV-2026-0001",
        "issue_date": "2026-10-01",
        "due_date": "2026-10-31",
        "currency": "USD",
        "subtotal": "1000.00",
        "tax": "240.00",
        "total": "1240.00",
        "bank_reference": "SYN-ACME-001",
        "po_reference": "PO-100",
        "line_items": [{"description": "Flour",
                        "quantity": "10",
                        "unit_price": "100.00"}],
    })
