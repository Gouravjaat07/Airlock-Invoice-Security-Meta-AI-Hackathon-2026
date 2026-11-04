"""Decimal candidate normalization for model-extracted amounts.

Model output copies printed characters (see EXTRACTION_INSTRUCTIONS);
this module converts unambiguous notations to canonical decimal strings
for the existing `parse_money` rules. Ambiguous notations raise
`UncertainNumberError` — callers drop the field (schema failure → R8),
never guess.
"""

from __future__ import annotations

import re
import unicodedata

_DIGITS = re.compile(r"^[0-9]+$")
_STD_GROUP = re.compile(r"^[0-9]{1,3}(,[0-9]{3})+$")
_IN_GROUP = re.compile(r"^[0-9]{1,2}(,[0-9]{2})*,[0-9]{3}$")

# Currency marks stripped from the edges (symbols, not semantics).
# Longer marks first: "Rs" must not shadow "Rs." ("Rs. 5,000" would
# otherwise leave a stray "." and fail as uncertain).
_CURRENCY_MARKS = ("Rs.", "$", "€", "£", "¥", "₹", "₩", "₽", "Rs",
                   "INR", "USD", "EUR", "GBP")


class UncertainNumberError(ValueError):
    """The notation is ambiguous; the field must stay unresolved."""


def _strip_marks(text: str) -> str:
    text = text.strip()
    changed = True
    while changed and text:
        changed = False
        for mark in _CURRENCY_MARKS:
            if text.startswith(mark):
                text = text[len(mark):].strip()
                changed = True
            elif text.endswith(mark):
                text = text[:-len(mark)].strip()
                changed = True
    return text


def normalize_decimal_candidate(raw: object) -> str:
    """Normalize one printed amount to `-?digits(.digits)?`.

    Raises UncertainNumberError on ambiguous or non-numeric input.
    """
    if isinstance(raw, bool):
        raise UncertainNumberError("boolean is not an amount")
    if isinstance(raw, (int,)):
        return str(raw)
    if not isinstance(raw, str):
        raise UncertainNumberError("amount must be a string")
    text = unicodedata.normalize("NFKC", raw).replace("\u00a0", " ").strip()
    if not text:
        raise UncertainNumberError("empty amount")
    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative = True
        text = text[1:-1].strip()
    if text.startswith("-"):
        negative = True
        text = text[1:].strip()
    elif text.startswith("+"):
        text = text[1:].strip()
    text = _strip_marks(text).replace(" ", "")
    if not text or any(ch not in "0123456789.," for ch in text):
        raise UncertainNumberError(f"non-numeric amount: {raw!r}"[:80])
    dots = text.count(".")
    commas = text.count(",")
    if dots and commas:
        # Last separator is the decimal mark; the other must group validly.
        if text.rfind(".") > text.rfind(","):
            integer, frac = text.rsplit(".", 1)
            if not _valid_grouping(integer, ","):
                raise UncertainNumberError(f"bad grouping: {raw!r}"[:80])
            integer = integer.replace(",", "")
        else:
            integer, frac = text.rsplit(",", 1)
            if not _valid_grouping(integer, "."):
                raise UncertainNumberError(f"bad grouping: {raw!r}"[:80])
            integer = integer.replace(".", "")
        if not integer or not _DIGITS.match(integer + frac):
            raise UncertainNumberError(f"bad amount: {raw!r}"[:80])
        out = f"{integer}.{frac}" if frac else integer
    elif commas:
        out = _single_separator(text, ",", raw)
    elif dots:
        out = _single_separator(text, ".", raw)
    else:
        if not _DIGITS.match(text):
            raise UncertainNumberError(f"bad amount: {raw!r}"[:80])
        out = text
    if negative and out != "0" and out != "0." + "0" * (len(out) - 2):
        out = "-" + out
    return out


def _valid_grouping(integer: str, sep: str) -> bool:
    if sep not in integer:
        return bool(_DIGITS.match(integer))
    if sep == ",":
        return bool(_STD_GROUP.match(integer) or _IN_GROUP.match(integer))
    return bool(re.match(r"^[0-9]{1,3}(\.[0-9]{3})+$", integer))


def _single_separator(text: str, sep: str, raw: object) -> str:
    if text.count(sep) > 1:
        # Repeated separator must be pure grouping (1,234,567).
        if sep == "," and _valid_grouping(text, ","):
            return text.replace(",", "")
        if sep == "." and re.match(r"^[0-9]{1,3}(\.[0-9]{3})+$", text):
            return text.replace(".", "")
        raise UncertainNumberError(f"bad grouping: {raw!r}"[:80])
    head, frac = text.split(sep, 1)
    if not head or not frac:
        raise UncertainNumberError(f"bad amount: {raw!r}"[:80])
    if len(frac) == 3 and len(head) <= 3 and _DIGITS.match(head):
        # "1,234" / "1.234": grouping or decimal? Ambiguous → refuse.
        raise UncertainNumberError(f"ambiguous amount: {raw!r}"[:80])
    if _DIGITS.match(head) and _DIGITS.match(frac):
        return f"{head}.{frac}"
    raise UncertainNumberError(f"bad amount: {raw!r}"[:80])


MONEY_FIELDS = ("subtotal", "tax", "total")
LINE_MONEY_FIELDS = ("quantity", "unit_price")


def normalize_extraction_numbers(payload: dict) -> tuple[dict, list[str]]:
    """Normalize money fields; drop ambiguous ones, return (cleaned, dropped).

    Dropped required fields fail local schema validation → R8 DENY.
    """
    cleaned = dict(payload)
    dropped: list[str] = []
    for name in MONEY_FIELDS:
        if name in cleaned:
            try:
                cleaned[name] = normalize_decimal_candidate(cleaned[name])
            except UncertainNumberError:
                del cleaned[name]
                dropped.append(name)
    items = cleaned.get("line_items")
    if isinstance(items, list):
        items = list(items)  # copy: never mutate the caller's list
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            item = dict(item)
            for name in LINE_MONEY_FIELDS:
                if name in item:
                    try:
                        item[name] = normalize_decimal_candidate(item[name])
                    except UncertainNumberError:
                        del item[name]
                        dropped.append(f"line_items[{index}].{name}")
            items[index] = item
        cleaned["line_items"] = items
    return cleaned, dropped
