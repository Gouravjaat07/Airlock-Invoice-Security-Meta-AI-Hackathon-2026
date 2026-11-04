"""Provider task contracts, normalized results, and typed errors.

Design rules: task-specific shapes only (no universal `generate(str)`);
every failure carries a machine-readable category plus a client-safe
message; secrets never appear in messages, details, or logs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from app.core.errors import AppError, ErrorCode


class ProviderName(str, Enum):
    META = "meta"  # Meta Model API (Spark, Voice, SAM)
    BASETEN = "baseten"  # hosted Muse Spark Open
    GLIMMER = "glimmer"  # local OpenAI-compatible runtime
    FIXTURE = "fixture"  # deterministic test double (dev/test only)
    MOCK = "mock"  # deterministic test double (dev/test only)


class TaskKind(str, Enum):
    INVOICE_EXTRACTION = "invoice_extraction"
    TRANSCRIPTION = "transcription"
    SEGMENTATION = "segmentation"


class ProviderErrorCategory(str, Enum):
    """Machine-readable failure classes (safe to expose as `details`)."""

    CONFIG = "config"  # missing credential/endpoint/model (operator fix)
    AUTH = "auth"  # provider rejected credentials (operator fix)
    BAD_REQUEST = "bad_request"  # provider refused the request shape
    RATE_LIMIT = "rate_limit"  # 429 / quota (retry later)
    TIMEOUT = "timeout"  # connect/read/stream deadline exceeded
    SERVER = "server"  # provider 5xx / gateway errors
    UNAVAILABLE = "unavailable"  # unreachable / refused / DNS / TLS
    MALFORMED = "malformed"  # unparseable or schema-invalid response
    REFUSAL = "refusal"  # provider refused the content
    INCOMPLETE = "incomplete"  # truncated/interrupted usable result


RETRYABLE = frozenset({
    ProviderErrorCategory.RATE_LIMIT,
    ProviderErrorCategory.TIMEOUT,
    ProviderErrorCategory.SERVER,
})


@dataclass(frozen=True)
class Usage:
    """Normalized usage metadata (only what the provider returned)."""

    provider_request_id: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    duration_ms: int = 0
    attempts: int = 1

    def as_dict(self) -> dict:
        return {
            "provider_request_id": self.provider_request_id,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "duration_ms": self.duration_ms,
            "attempts": self.attempts,
        }


class ProviderError(Exception):
    """Typed provider failure. `message` is always client-safe."""

    def __init__(self, category: ProviderErrorCategory, message: str, *,
                 provider: ProviderName | None = None,
                 provider_request_id: str | None = None,
                 retry_after_s: float | None = None) -> None:
        super().__init__(message)
        self.category = category
        self.message = message
        self.provider = provider
        self.provider_request_id = provider_request_id
        self.retry_after_s = retry_after_s

    @property
    def retryable(self) -> bool:
        return self.category in RETRYABLE


def to_app_error(exc: ProviderError) -> AppError:
    """Map a provider failure onto the stable API error taxonomy."""
    if exc.category == ProviderErrorCategory.RATE_LIMIT:
        return AppError(ErrorCode.RATE_LIMIT,
                       "Model provider rate limited; retry later",
                       details=[{"code": exc.category.value}])
    return AppError(ErrorCode.API_UNAVAILABLE, "Model provider unavailable",
                    details=[{"code": exc.category.value}])


@dataclass(frozen=True)
class TranscriptTurn:
    """One validated transcript turn (turn-level timing only)."""

    turn_id: str
    start_ms: int
    end_ms: int
    text: str
    speaker: str | None = None


@dataclass
class ModelResult:
    """Normalized envelope shared by all task results."""

    provider: ProviderName
    model: str
    task: TaskKind
    usage: Usage = field(default_factory=Usage)
    prompt_version: str = "n/a"
    warnings: list[str] = field(default_factory=list)
