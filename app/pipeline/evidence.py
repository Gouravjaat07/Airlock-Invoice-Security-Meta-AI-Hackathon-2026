"""Optional-evidence lane outcomes (voice transcription, SAM segmentation).

A lane is one provider task over one evidence artifact. The outcome
records whether the provider ran AND whether the deterministic
comparison against the invoice ran: an uploaded artifact whose lane
never evaluated is NOT_EVALUATED, never silent confirmation.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class LaneStatus(str, Enum):
    MISSING = "missing"  # no artifact uploaded for this lane
    EVALUATED = "evaluated"  # provider ran; comparison ran
    NOT_EVALUATED = "not_evaluated"  # uploaded; comparison could not run
    FAILED = "failed"  # provider/transport/integrity error
    EMPTY = "empty"  # provider succeeded with zero usable content


@dataclass(frozen=True)
class LaneOutcome:
    """Typed result of one evidence lane."""

    lane: str  # "voice" | "sam"
    status: LaneStatus
    conflict: bool = False
    detail: str = ""

    @property
    def evaluated(self) -> bool:
        return self.status == LaneStatus.EVALUATED
