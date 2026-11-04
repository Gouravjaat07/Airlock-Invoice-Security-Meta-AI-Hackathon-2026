"""Case state machine: legal transitions only, audit-logged by callers."""

from __future__ import annotations

from app.core.errors import AppError, ErrorCode
from app.domain.enums import CaseState

TRANSITIONS: dict[CaseState, frozenset[CaseState]] = {
    CaseState.UPLOADED: frozenset({CaseState.READING, CaseState.CANCELLED, CaseState.ERROR}),
    CaseState.READING: frozenset({CaseState.CORROBORATING, CaseState.ERROR, CaseState.CANCELLED}),
    CaseState.CORROBORATING: frozenset({CaseState.VERDICT, CaseState.ERROR, CaseState.CANCELLED}),
    CaseState.VERDICT: frozenset({
        CaseState.PROPOSED, CaseState.REJECTED, CaseState.NEEDS_REVIEW,
        CaseState.ERROR, CaseState.CANCELLED,
    }),
    CaseState.PROPOSED: frozenset({
        CaseState.READING,  # explicit re-run after a trusted event (owner edit)
        CaseState.CONFIRMED, CaseState.EXPIRED, CaseState.CANCELLED,
        CaseState.NEEDS_REVIEW, CaseState.ERROR,
    }),
    CaseState.CONFIRMED: frozenset({CaseState.EXECUTED, CaseState.ERROR}),
    CaseState.EXECUTED: frozenset(),
    CaseState.REJECTED: frozenset({CaseState.READING}),  # explicit re-run after trusted event
    CaseState.NEEDS_REVIEW: frozenset({CaseState.READING, CaseState.CANCELLED, CaseState.REJECTED}),
    CaseState.ERROR: frozenset({CaseState.READING, CaseState.CANCELLED}),
    CaseState.CANCELLED: frozenset(),
    CaseState.EXPIRED: frozenset({CaseState.READING}),
}


def check_transition(current: CaseState, nxt: CaseState) -> None:
    if nxt not in TRANSITIONS.get(current, frozenset()):
        raise AppError(ErrorCode.STATE_TRANSITION,
                       f"Illegal case transition {current.value} -> {nxt.value}")
