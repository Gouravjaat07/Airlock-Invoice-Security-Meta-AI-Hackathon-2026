"""Payment adapters: mock-only execution boundary.

Phase 2 implements exactly one executor: the local mock executor, which
writes a MOCK payment record to the local database and makes no network
requests. There is no real-payment adapter, no provider abstraction, and
no credential-bearing payment configuration -- by design.
"""

from __future__ import annotations

from typing import Protocol

MOCK_LABEL = "MOCK PAYMENT \u2014 NO MONEY TRANSFERRED"


class PaymentExecutor(Protocol):
    executor_id: str

    def execute(self, **kwargs: object) -> dict:
        ...
