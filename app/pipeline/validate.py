"""Schema validation of tainted reader output.

Parses raw reader JSON into `InvoiceExtraction`. Schema-valid means
well-formed, never true: output stays T2 and must still pass registry,
arithmetic, duplicate, and policy checks.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from app.core.errors import AppError, ErrorCode
from app.providers.currency import (
    UncertainCurrencyError,
    normalize_currency_candidate,
)
from app.schemas.invoice import InvoiceExtraction


def validate_extraction(payload: Any) -> InvoiceExtraction:
    if not isinstance(payload, dict):
        raise AppError(ErrorCode.SCHEMA, "Reader output must be a JSON object",
                       details=[{"code": "not-an-object"}])
    # Deterministic currency normalization before strict Pydantic checks.
    # The `InvoiceExtraction` pattern stays `^[A-Z]{3}$` (never weakened);
    # safe cases (`usd` -> `USD`, unambiguous names/symbols) normalize here
    # so mocked and live paths share one rule, while ambiguous values fail
    # with an actionable message instead of a bare pattern mismatch.
    if "currency" in payload:
        try:
            normalized = normalize_currency_candidate(payload["currency"])
        except UncertainCurrencyError as exc:
            raise AppError(ErrorCode.SCHEMA,
                           "Reader output failed schema validation",
                           details=[{"code": "currency",
                                     "message": str(exc)}]) from exc
        if normalized != payload["currency"]:
            payload = {**payload, "currency": normalized}
    try:
        return InvoiceExtraction.model_validate(payload)
    except ValidationError as exc:
        details = [
            {"code": ".".join(str(part) for part in err["loc"]) or "root",
             "message": err["msg"]}
            for err in exc.errors()
        ]
        raise AppError(ErrorCode.SCHEMA, "Reader output failed schema validation",
                       details=details) from exc
