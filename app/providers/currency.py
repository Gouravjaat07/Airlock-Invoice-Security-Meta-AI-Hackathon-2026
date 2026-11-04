"""Deterministic currency normalization for model-extracted values.

The model copies printed characters; this module converts only
unambiguous notations to ISO 4217 alphabetic codes. Ambiguous or
unrecognized values raise `UncertainCurrencyError` with an actionable
message — callers surface it as a schema failure (R8), never guess.

Rules:
- `USD` (any `[A-Za-z]{3}`) uppercases safely to `USD`.
- Unambiguous names/symbols map only when the string itself identifies
  one currency (`euro` -> EUR, `US$` -> USD, `INR` symbol -> INR).
- `$` alone is ambiguous (USD/CAD/AUD/...) — never infer USD.
- Missing/empty/malformed/unsupported values fail with guidance.
"""

from __future__ import annotations

import re
import unicodedata

_CODE_RE = re.compile(r"^[A-Za-z]{3}$")
_MAX_ECHO = 32


class UncertainCurrencyError(ValueError):
    """Currency cannot be resolved deterministically; actionable message."""


def _short(value: object) -> str:
    text = value if isinstance(value, str) else repr(value)
    text = text.replace("\n", " ").replace("\r", " ")[:_MAX_ECHO]
    return text


# Unambiguous symbols only. `$`, `¥`, `₩`, `Rs` are intentionally absent:
# each maps to several currencies and must fail as ambiguous.
_SYMBOL_TO_CODE = {
    "\u20ac": "EUR",  # €
    "\u20b9": "INR",  # ₹
    "\u00a3": "GBP",  # £ (sterling; qualified names disambiguate other pounds)
    "\u20bd": "RUB",  # ₽
    "\u20b4": "UAH",  # ₴
    "\u20ba": "TRY",  # ₺
    "US$": "USD",
}

# Lowercased, dots stripped, whitespace collapsed.
_NAME_TO_CODE = {
    "us dollar": "USD",
    "us dollars": "USD",
    "united states dollar": "USD",
    "united states dollars": "USD",
    "euro": "EUR",
    "euros": "EUR",
    "british pound": "GBP",
    "british pounds": "GBP",
    "pound sterling": "GBP",
    "sterling": "GBP",
    "indian rupee": "INR",
    "indian rupees": "INR",
    "japanese yen": "JPY",
    "yen": "JPY",
    "chinese yuan": "CNY",
    "yuan": "CNY",
    "renminbi": "CNY",
    "chinese renminbi": "CNY",
    "canadian dollar": "CAD",
    "canadian dollars": "CAD",
    "australian dollar": "AUD",
    "australian dollars": "AUD",
    "swiss franc": "CHF",
    "swiss francs": "CHF",
    "mexican peso": "MXN",
    "mexican pesos": "MXN",
    "russian ruble": "RUB",
    "russian rubles": "RUB",
    "ukrainian hryvnia": "UAH",
    "turkish lira": "TRY",
    "south korean won": "KRW",
    "new zealand dollar": "NZD",
    "new zealand dollars": "NZD",
    "hong kong dollar": "HKD",
    "hong kong dollars": "HKD",
    "singapore dollar": "SGD",
    "singapore dollars": "SGD",
}

_AMBIGUOUS_SYMBOLS = frozenset({"$", "\u00a5", "\u20a9", "Rs", "Rs.", "R$"})
_AMBIGUOUS_NAMES = frozenset({
    "dollar", "dollars", "pound", "pounds", "rupee", "rupees",
    "franc", "francs", "won", "peso", "pesos", "lira", "ruble",
    "rubles", "krone", "krona", "ringgit", "rand",
})


def _collapse(text: str) -> str:
    return " ".join(text.split())


def normalize_currency_candidate(raw: object) -> str:
    """Normalize one currency value to an ISO 4217 alphabetic code.

    Raises UncertainCurrencyError with an actionable message when the
    value is missing, malformed, ambiguous, or unsupported.
    """
    if isinstance(raw, bool):
        raise UncertainCurrencyError(
            "Currency must be the ISO 4217 alphabetic code "
            "(e.g. USD, EUR, INR), not a boolean.")
    if raw is None:
        raise UncertainCurrencyError(
            "Currency is missing; provide the ISO 4217 alphabetic code "
            "(e.g. USD, EUR, INR). Do not use symbols or names.")
    if not isinstance(raw, str):
        raise UncertainCurrencyError(
            f"Unsupported currency {_short(raw)!r}; provide the ISO 4217 "
            "alphabetic code (e.g. USD, EUR, INR).")
    text = unicodedata.normalize("NFKC", raw).replace("\u00a0", " ").strip()
    if not text:
        raise UncertainCurrencyError(
            "Currency is missing or ambiguous; provide the ISO 4217 "
            "alphabetic code (e.g. USD, EUR, INR). Do not default to USD.")
    # Names/symbols first: 3-letter words like `yen`/`won` must map (or
    # fail as ambiguous) before the generic 3-letter code rule, or `yen`
    # would wrongly become `YEN` instead of `JPY`.
    nospace = text.replace(" ", "")
    if nospace in _SYMBOL_TO_CODE:
        return _SYMBOL_TO_CODE[nospace]
    upper_nospace = "".join(
        ch.upper() if "a" <= ch <= "z" or "A" <= ch <= "Z" else ch
        for ch in nospace
    )
    if upper_nospace in _SYMBOL_TO_CODE:
        return _SYMBOL_TO_CODE[upper_nospace]
    if text in _SYMBOL_TO_CODE:
        return _SYMBOL_TO_CODE[text]
    if nospace in _AMBIGUOUS_SYMBOLS or text in _AMBIGUOUS_SYMBOLS:
        raise UncertainCurrencyError(
            f"Ambiguous currency symbol {_short(text)!r}; several currencies "
            "share it. Provide the ISO 4217 alphabetic code (e.g. USD, CAD, "
            "AUD for '$'; JPY or CNY for '¥'). Never assume USD from '$' alone.")
    lowered = _collapse(text.replace(".", "").lower())
    if lowered in _NAME_TO_CODE:
        return _NAME_TO_CODE[lowered]
    if lowered in _AMBIGUOUS_NAMES:
        raise UncertainCurrencyError(
            f"Ambiguous currency name {_short(text)!r}; several currencies "
            "share it. Provide the ISO 4217 alphabetic code (e.g. USD for "
            "'US dollars', CAD for 'Canadian dollars').")
    if _CODE_RE.match(text):
        return text.upper()
    raise UncertainCurrencyError(
        f"Unsupported currency {_short(text)!r}; provide the ISO 4217 "
        "alphabetic code (e.g. USD, EUR, INR), not the symbol or name.")
