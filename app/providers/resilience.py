"""Retry, backoff, circuit-breaking, and inflight limits (sync).

All primitives are thread-safe and free of `asyncio` (harness-safe).
Retries apply ONLY to understood-transient categories (rate limit,
timeout, server); ambiguous acceptance after a timeout is surfaced to
the caller as TIMEOUT (reconciliation state), never auto-retried beyond
the bounded policy, and POSTs are never assumed idempotent.
"""

from __future__ import annotations

import random
import threading
import time
from typing import Callable, TypeVar

from app.core.clock import SYSTEM_CLOCK
from app.core.logging import get_logger
from app.providers.types import (
    ProviderError,
    ProviderErrorCategory,
    ProviderName,
)

logger = get_logger("airlock.providers.resilience")

# Fixed resilience semantics (documented; not business thresholds).
BACKOFF_BASE_S = 1.0
BACKOFF_CAP_S = 30.0
BREAKER_THRESHOLD = 5  # consecutive failures to open
BREAKER_COOLDOWN_S = 60.0

T = TypeVar("T")

# Breaker counts provider-side failures only; client/config errors and
# content refusals are deterministic, not outage signals.
BREAKER_CATEGORIES = frozenset({
    ProviderErrorCategory.TIMEOUT,
    ProviderErrorCategory.SERVER,
    ProviderErrorCategory.RATE_LIMIT,
    ProviderErrorCategory.UNAVAILABLE,
})


def compute_backoff(attempt: int, *, retry_after_s: float | None = None,
                    rand: Callable[[], float] | None = None) -> float:
    """Bounded exponential backoff with jitter; honors Retry-After."""
    if retry_after_s is not None:
        return max(0.0, min(retry_after_s, BACKOFF_CAP_S))
    raw = min(BACKOFF_BASE_S * (2.0 ** max(0, attempt)), BACKOFF_CAP_S)
    jitter = (rand() if rand is not None else random.random()) * raw * 0.25
    return raw + jitter


def run_with_retries(label: str, fn: Callable[[int], T], *,
                     max_retries: int,
                     sleeper: Callable[[float], None] = time.sleep,
                     rand: Callable[[], float] | None = None) -> T:
    """Run `fn(attempt)`; retry transient ProviderErrors with backoff.

    Returns the first success. Raises the last ProviderError when the
    budget is exhausted or the failure is non-retryable.
    """
    attempt = 0
    while True:
        try:
            return fn(attempt)
        except ProviderError as exc:
            if not exc.retryable or attempt >= max_retries:
                raise
            delay = compute_backoff(attempt,
                                    retry_after_s=exc.retry_after_s, rand=rand)
            logger.warning("provider retry op=%s attempt=%d category=%s delay=%.2f",
                           label, attempt + 1, exc.category.value, delay)
            sleeper(delay)
            attempt += 1


class ProviderBreaker:
    """Minimal consecutive-failure circuit breaker (sync, testable)."""

    def __init__(self, *, threshold: int = BREAKER_THRESHOLD,
                 cooldown_s: float = BREAKER_COOLDOWN_S) -> None:
        self._threshold = threshold
        self._cooldown_s = cooldown_s
        self._lock = threading.Lock()
        self._failures = 0
        self._opened_at: float | None = None

    def allow(self) -> bool:
        """True when calls may proceed (closed, or cooldown elapsed)."""
        with self._lock:
            if self._opened_at is None:
                return True
            elapsed = time.monotonic() - self._opened_at
            if elapsed >= self._cooldown_s:
                self._opened_at = None  # half-open: one probe call allowed
                self._failures = 0
                return True
            return False

    @property
    def is_open(self) -> bool:
        return not self.allow()

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_at = None

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._failures >= self._threshold and self._opened_at is None:
                self._opened_at = time.monotonic()
                logger.warning("provider breaker opened failures=%d",
                               self._failures)

    @property
    def state(self) -> str:
        with self._lock:
            if self._opened_at is None:
                return "closed" if self._failures == 0 else "monitoring"
            return "open"


class ProviderGuards:
    """Per-provider breakers + inflight semaphores (process-lifetime)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._breakers: dict[str, ProviderBreaker] = {}
        self._semaphores: dict[str, threading.BoundedSemaphore] = {}

    def breaker(self, name: ProviderName | str) -> ProviderBreaker:
        key = str(name)
        with self._lock:
            breaker = self._breakers.get(key)
            if breaker is None:
                breaker = ProviderBreaker()
                self._breakers[key] = breaker
            return breaker

    def semaphore(self, name: ProviderName | str, limit: int
                  ) -> threading.BoundedSemaphore:
        key = f"{name}:{limit}"
        with self._lock:
            semaphore = self._semaphores.get(key)
            if semaphore is None:
                semaphore = threading.BoundedSemaphore(limit)
                self._semaphores[key] = semaphore
            return semaphore

    def reset_for_tests(self) -> None:
        with self._lock:
            self._breakers = {}
            self._semaphores = {}


GUARDS = ProviderGuards()


def utc_ms() -> int:
    return int(SYSTEM_CLOCK.now().timestamp() * 1000)


def call_guarded(provider: ProviderName, label: str,
                 fn: Callable[[int], T], *, max_inflight: int,
                 max_retries: int) -> tuple[T, int]:
    """Breaker + inflight limit + bounded retries around one provider call.

    Returns (result, attempts_used). Raises ProviderError (fail closed).
    """
    breaker = GUARDS.breaker(provider)
    if not breaker.allow():
        raise ProviderError(ProviderErrorCategory.UNAVAILABLE,
                            "Provider temporarily unavailable after repeated "
                            "failures", provider=provider)
    semaphore = GUARDS.semaphore(provider, max_inflight)
    semaphore.acquire()  # bounded upstream; single lock level, no deadlock
    try:
        used = {"attempts": 1}

        def _wrapped(attempt: int) -> T:
            used["attempts"] = attempt + 1
            return fn(attempt)

        try:
            out = run_with_retries(label, _wrapped, max_retries=max_retries)
        except ProviderError as exc:
            if exc.category in BREAKER_CATEGORIES:
                breaker.record_failure()
            raise
        breaker.record_success()
        return out, used["attempts"]
    finally:
        semaphore.release()
