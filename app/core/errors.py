"""Application error taxonomy.

Every API failure maps to a stable `E_*` code in a uniform envelope.
Internal details stay server-side; only safe messages reach clients.
"""

from __future__ import annotations


class ErrorCode:
    UPLOAD = "E_UPLOAD"
    SCHEMA = "E_SCHEMA"
    READER_UNAVAILABLE = "E_READER_UNAVAILABLE"
    READER_TIMEOUT = "E_READER_TIMEOUT"
    API_UNAVAILABLE = "E_API_UNAVAILABLE"
    AUTH = "E_AUTH"
    RATE_LIMIT = "E_RATE_LIMIT"
    EXPIRED = "E_EXPIRED"
    DUPLICATE = "E_DUPLICATE"
    POLICY_DENY = "E_POLICY_DENY"
    POLICY_ESCALATE = "E_POLICY_ESCALATE"
    CONFLICT = "E_CONFLICT"
    STATE_TRANSITION = "E_STATE_TRANSITION"
    AUDIT = "E_AUDIT"
    STORAGE = "E_STORAGE"
    DATABASE = "E_DATABASE"
    INTERNAL = "E_INTERNAL"


# Safe default HTTP status per code.
STATUS_BY_CODE = {
    ErrorCode.UPLOAD: 400,
    ErrorCode.SCHEMA: 422,
    ErrorCode.READER_UNAVAILABLE: 503,
    ErrorCode.READER_TIMEOUT: 504,
    ErrorCode.API_UNAVAILABLE: 503,
    ErrorCode.AUTH: 401,
    ErrorCode.RATE_LIMIT: 429,
    ErrorCode.EXPIRED: 410,
    ErrorCode.DUPLICATE: 409,
    ErrorCode.POLICY_DENY: 422,
    ErrorCode.POLICY_ESCALATE: 422,
    ErrorCode.CONFLICT: 409,
    ErrorCode.STATE_TRANSITION: 409,
    ErrorCode.AUDIT: 500,
    ErrorCode.STORAGE: 500,
    ErrorCode.DATABASE: 500,
    ErrorCode.INTERNAL: 500,
}


class AppError(Exception):
    """Raised by services/pipeline; rendered as the error envelope."""

    def __init__(self, code: str, message: str, *, details: list | None = None,
                 status: int | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or []
        self.status = status if status is not None else STATUS_BY_CODE.get(code, 500)
