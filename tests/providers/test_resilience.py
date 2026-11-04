"""Resilience tests: backoff, retries, breaker, inflight guards."""

from __future__ import annotations

import threading
import time

import pytest

from app.providers.resilience import (
    GUARDS,
    ProviderBreaker,
    call_guarded,
    compute_backoff,
    run_with_retries,
)
from app.providers.types import ProviderError, ProviderErrorCategory, ProviderName


def _err(category):
    return ProviderError(category, "x", provider=ProviderName.META)


def test_backoff_bounds_and_jitter():
    assert compute_backoff(0, rand=lambda: 0.0) == 1.0
    assert compute_backoff(0, rand=lambda: 1.0) == 1.25
    assert compute_backoff(99, rand=lambda: 0.0) == 30.0
    assert compute_backoff(0, retry_after_s=5.0) == 5.0
    assert compute_backoff(0, retry_after_s=999.0) == 30.0


def test_retry_transient_then_success():
    calls = []

    def fn(attempt):
        calls.append(attempt)
        if attempt < 2:
            raise _err(ProviderErrorCategory.SERVER)
        return "ok"

    slept = []
    out = run_with_retries("op", fn, max_retries=3,
                           sleeper=slept.append, rand=lambda: 0.0)
    assert out == "ok"
    assert calls == [0, 1, 2]
    assert slept == [1.0, 2.0]


@pytest.mark.parametrize("category", [
    ProviderErrorCategory.RATE_LIMIT,
    ProviderErrorCategory.TIMEOUT,
    ProviderErrorCategory.SERVER,
])
def test_retryable_categories_exhaust_budget(category):
    calls = []

    def fn(attempt):
        calls.append(attempt)
        raise _err(category)

    with pytest.raises(ProviderError):
        run_with_retries("op", fn, max_retries=2, sleeper=lambda s: None,
                         rand=lambda: 0.0)
    assert calls == [0, 1, 2]


@pytest.mark.parametrize("category", [
    ProviderErrorCategory.AUTH,
    ProviderErrorCategory.CONFIG,
    ProviderErrorCategory.BAD_REQUEST,
    ProviderErrorCategory.MALFORMED,
    ProviderErrorCategory.REFUSAL,
    ProviderErrorCategory.INCOMPLETE,
    ProviderErrorCategory.UNAVAILABLE,
])
def test_non_retryable_single_attempt(category):
    calls = []

    def fn(attempt):
        calls.append(attempt)
        raise _err(category)

    with pytest.raises(ProviderError):
        run_with_retries("op", fn, max_retries=3, sleeper=lambda s: None)
    assert calls == [0]


def test_breaker_opens_and_recovers(monkeypatch):
    breaker = ProviderBreaker(threshold=3, cooldown_s=60.0)
    assert breaker.allow() is True
    assert breaker.state == "closed"
    breaker.record_failure()
    breaker.record_failure()
    assert breaker.state == "monitoring"
    breaker.record_failure()
    assert breaker.allow() is False
    assert breaker.state == "open"
    breaker.record_success()  # manual reset path still works
    assert breaker.allow() is True


def test_breaker_cooldown_expiry(monkeypatch):
    breaker = ProviderBreaker(threshold=1, cooldown_s=10.0)
    breaker.record_failure()
    assert breaker.is_open is True
    now = time.monotonic()
    monkeypatch.setattr(time, "monotonic", lambda: now + 11.0)
    assert breaker.allow() is True


def test_call_guarded_counts_attempts_and_breaker():
    def fn(attempt):
        if attempt == 0:
            raise _err(ProviderErrorCategory.TIMEOUT)
        return "done"

    out, attempts = call_guarded(ProviderName.META, "op", fn,
                                 max_inflight=2, max_retries=2)
    assert (out, attempts) == ("done", 2)
    assert GUARDS.breaker(ProviderName.META).state == "closed"


def test_call_guarded_refuses_when_open():
    breaker = GUARDS.breaker(ProviderName.BASETEN)
    for _ in range(5):
        breaker.record_failure()
    with pytest.raises(ProviderError) as exc_info:
        call_guarded(ProviderName.BASETEN, "op", lambda a: "x",
                     max_inflight=2, max_retries=0)
    assert exc_info.value.category == ProviderErrorCategory.UNAVAILABLE


def test_call_guarded_ignores_client_errors_for_breaker():
    def fn(attempt):
        raise _err(ProviderErrorCategory.BAD_REQUEST)

    with pytest.raises(ProviderError):
        call_guarded(ProviderName.GLIMMER, "op", fn, max_inflight=2,
                     max_retries=0)
    assert GUARDS.breaker(ProviderName.GLIMMER).state == "closed"


def test_semaphore_serializes():
    sem = GUARDS.semaphore(ProviderName.META, 1)
    order = []
    entered = threading.Event()

    def worker(name, hold):
        with sem:
            order.append(f"{name}-in")
            entered.set()
            time.sleep(hold)
            order.append(f"{name}-out")

    first = threading.Thread(target=worker, args=("a", 0.2))
    first.start()
    assert entered.wait(timeout=5)
    second = threading.Thread(target=worker, args=("b", 0.0))
    second.start()
    first.join(timeout=5)
    second.join(timeout=5)
    assert order == ["a-in", "a-out", "b-in", "b-out"]
