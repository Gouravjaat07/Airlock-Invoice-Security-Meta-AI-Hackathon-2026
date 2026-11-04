"""Taint classes T0-T3.

T0 owner input, T1 trusted config/registry, T2 tainted model output,
T3 raw artifacts. T2/T3 values never authorize actions.
"""

from __future__ import annotations

from enum import Enum


class TaintClass(str, Enum):
    T0_OWNER = "T0"
    T1_TRUSTED = "T1"
    T2_MODEL = "T2"
    T3_RAW = "T3"


AUTHORITATIVE = frozenset({TaintClass.T0_OWNER, TaintClass.T1_TRUSTED})


def is_authoritative(taint: TaintClass) -> bool:
    return taint in AUTHORITATIVE
