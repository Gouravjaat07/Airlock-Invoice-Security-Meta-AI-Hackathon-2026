"""Airlock Phase 2 application core.

Deterministic, injection-resistant accounts-payable backend. Trust model:
T0 owner input, T1 trusted config/registry, T2 tainted model output,
T3 raw untrusted artifacts. Only T0/T1 can authorize; T2/T3 never do.
"""

__version__ = "0.1.0"
