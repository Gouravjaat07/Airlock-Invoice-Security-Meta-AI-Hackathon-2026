"""Shared model-extraction finalizer (Spark / Spark Open / Glimmer).

One code path turns raw model JSON text into a `ReaderResult`-ready
payload: strict JSON parse, allowlist to the `InvoiceExtraction` field
set (unknown fields dropped with warnings, never trusted), decimal
normalization (ambiguous amounts dropped → R8), and evidence-anchor
grounding (invalid page refs dropped, never repaired).
"""

from __future__ import annotations

import json
from typing import Any

from app.adapters.readers import ReaderResult
from app.core.errors import AppError, ErrorCode
from app.providers.currency import (
    UncertainCurrencyError,
    normalize_currency_candidate,
)
from app.providers.numbers import normalize_extraction_numbers
from app.providers.prompts import EXTRACTION_SCHEMA_VERSION
from app.providers.types import (
    ModelResult,
    ProviderError,
    ProviderErrorCategory,
    ProviderName,
    TaskKind,
    Usage,
)

MAX_JSON_CHARS = 200_000


def content_error(exc: ProviderError) -> AppError:
    """Map unusable model *content* to a schema failure (R8 DENY).

    Used only after a completed provider response arrived: the transport
    worked, but the output cannot serve as an extraction. Transport and
    protocol failures keep `to_app_error` (retryable ERROR state).
    """
    return AppError(ErrorCode.SCHEMA, "Model output failed validation",
                    details=[{"code": exc.category.value}])

KNOWN_FIELDS = frozenset({
    "vendor_name", "invoice_number", "issue_date", "due_date", "currency",
    "subtotal", "tax", "total", "bank_reference", "po_reference",
    "line_items", "evidence",
})
KNOWN_ITEM_FIELDS = frozenset({"description", "quantity", "unit_price"})

# Renamed required fields (normalized: casefold, strip separators).
# A renamed field is a missing field: fail with an explicit error naming
# the required field, never silently drop it or guess-merge the value.
_FIELD_ALIASES = {
    "vendor": "vendor_name",
    "invoiceno": "invoice_number",
    "invoicenumber": "invoice_number",
    "issuedate": "issue_date",
    "duedate": "due_date",
}
_ITEM_ALIASES = {
    "qty": "quantity",
    "unitprice": "unit_price",
    "price": "unit_price",
}


def _normalized_key(key: Any) -> str | None:
    if not isinstance(key, str):
        return None
    return "".join(ch for ch in key.casefold() if ch.isalnum())


def parse_model_json(text: str, *, provider: ProviderName) -> dict[str, Any]:
    """Parse model output text as a JSON object (strict, bounded)."""
    stripped = (text or "").strip()
    if not stripped:
        raise ProviderError(ProviderErrorCategory.MALFORMED,
                            "Provider returned empty output",
                            provider=provider)
    if len(stripped) > MAX_JSON_CHARS:
        raise ProviderError(ProviderErrorCategory.MALFORMED,
                            "Provider output exceeded size limit",
                            provider=provider)
    try:
        parsed = json.loads(stripped)
    except ValueError as exc:
        raise ProviderError(ProviderErrorCategory.MALFORMED,
                            "Provider output is not valid JSON",
                            provider=provider) from exc
    if not isinstance(parsed, dict):
        raise ProviderError(ProviderErrorCategory.MALFORMED,
                            "Provider output is not a JSON object",
                            provider=provider)
    return parsed


_WARNING_KEY_CHARS = 64


def _short_key(key: Any) -> str:
    # Warning strings travel into audit payloads and API responses:
    # model-controlled key names are truncated, never embedded whole.
    text = key if isinstance(key, str) else repr(key)
    return text[:_WARNING_KEY_CHARS]


def allowlist_payload(payload: dict[str, Any], *,
                      provider: ProviderName | None = None
                      ) -> tuple[dict[str, Any], list[str]]:
    """Keep only `InvoiceExtraction` fields (+evidence); warn on drops.

    Known renames of required fields (e.g. `qty` for `quantity`) raise
    an explicit error instead: the model violated the schema contract,
    and a silent drop would surface later as a cryptic missing field.
    """
    warnings: list[str] = []
    cleaned: dict[str, Any] = {}
    for key, value in payload.items():
        if key not in KNOWN_FIELDS:
            normalized = _normalized_key(key)
            if normalized in _FIELD_ALIASES:
                required = _FIELD_ALIASES[normalized]
                raise ProviderError(
                    ProviderErrorCategory.MALFORMED,
                    f"Model used {normalized!r}: the required field "
                    f"name is {required!r}",
                    provider=provider)
            warnings.append(f"dropped unknown field {_short_key(key)!r}")
            continue
        cleaned[key] = value
    items = cleaned.get("line_items")
    if isinstance(items, list):
        kept_items = []
        for item in items:
            if not isinstance(item, dict):
                kept_items.append(item)
                continue
            for name in item:
                normalized = _normalized_key(name)
                if name not in KNOWN_ITEM_FIELDS and normalized in _ITEM_ALIASES:
                    required = _ITEM_ALIASES[normalized]
                    raise ProviderError(
                        ProviderErrorCategory.MALFORMED,
                        f"Model used {normalized!r}: the required line-item "
                        f"field name is {required!r}",
                        provider=provider)
            kept = {k: v for k, v in item.items() if k in KNOWN_ITEM_FIELDS}
            dropped = sorted(set(item) - KNOWN_ITEM_FIELDS)
            if dropped:
                names = [_short_key(name) for name in dropped[:8]]
                warnings.append(f"dropped unknown line-item fields {names}")
            kept_items.append(kept)
        cleaned["line_items"] = kept_items
    return cleaned, warnings


def ground_evidence(payload: dict[str, Any], *, page_count: int,
                    image_dims: tuple[int, int] | None) -> list[str]:
    """Validate `evidence.pages` anchors in place; drop the block if invalid.

    Returns warnings. Values are candidates regardless; only the anchors
    are verified here (page existence; images must cite page 1).
    """
    warnings: list[str] = []
    evidence = payload.get("evidence")
    if evidence is None:
        return warnings
    if not isinstance(evidence, dict):
        warnings.append("dropped malformed evidence block")
        payload.pop("evidence", None)
        return warnings
    pages = evidence.get("pages")
    if pages is None:
        payload.pop("evidence", None)
        return warnings
    if not isinstance(pages, dict):
        warnings.append("dropped malformed evidence pages")
        payload.pop("evidence", None)
        return warnings
    for field_name, page in pages.items():
        if (not isinstance(page, int) or isinstance(page, bool)
                or page < 1 or page > page_count):
            warnings.append(f"dropped evidence: {field_name!r} cites "
                            f"invalid page {page!r}")
            payload.pop("evidence", None)
            return warnings
    if image_dims is not None:
        width, height = image_dims
        if width <= 0 or height <= 0:
            warnings.append("dropped evidence: invalid image dimensions")
            payload.pop("evidence", None)
    return warnings


def finalize_extraction(raw_text: str, *, provider: ProviderName, model: str,
                        prompt_version: str, artifact_sha256: str,
                        page_count: int,
                        image_dims: tuple[int, int] | None,
                        usage: Usage,
                        request_id: str | None) -> tuple[ReaderResult, ModelResult]:
    """Full finalize path shared by all extraction readers."""
    parsed = parse_model_json(raw_text, provider=provider)
    cleaned, warnings = allowlist_payload(parsed, provider=provider)
    cleaned, dropped = normalize_extraction_numbers(cleaned)
    if dropped:
        warnings.append(f"ambiguous amounts dropped: {sorted(dropped)}")
    if "currency" in cleaned:
        raw_currency = cleaned["currency"]
        try:
            normalized = normalize_currency_candidate(raw_currency)
        except UncertainCurrencyError:
            # Leave the raw value for schema validation to reject with an
            # actionable message; never guess or default here.
            pass
        else:
            if normalized != raw_currency:
                cleaned["currency"] = normalized
                warnings.append(
                    f"currency normalized {str(raw_currency)[:16]!r} "
                    f"-> {normalized!r}")
    warnings.extend(ground_evidence(cleaned, page_count=page_count,
                                    image_dims=image_dims))
    # The evidence block is provenance metadata, not invoice data: keep
    # the grounded page anchors for fact sources, then strip the block
    # so the payload matches `InvoiceExtraction` exactly (it forbids
    # extras, and would otherwise reject every evidence-bearing output).
    evidence_pages: dict[str, int] | None = None
    evidence = cleaned.pop("evidence", None)
    if isinstance(evidence, dict):
        pages = evidence.get("pages")
        if isinstance(pages, dict) and pages:
            evidence_pages = {str(name): int(page)
                              for name, page in pages.items()
                              if isinstance(page, int)
                              and not isinstance(page, bool) and page >= 1}
            if not evidence_pages:
                evidence_pages = None
    result = ModelResult(provider=provider, model=model,
                         task=TaskKind.INVOICE_EXTRACTION, usage=usage,
                         prompt_version=prompt_version,
                         warnings=warnings)
    reader_result = ReaderResult(
        payload=cleaned, artifact_sha256=artifact_sha256, scenario="",
        request_id=request_id, model_id=model,
        prompt_version=prompt_version,
        usage={**usage.as_dict(), "schema_version": EXTRACTION_SCHEMA_VERSION},
        warnings=tuple(warnings), evidence_pages=evidence_pages)
    return reader_result, result
