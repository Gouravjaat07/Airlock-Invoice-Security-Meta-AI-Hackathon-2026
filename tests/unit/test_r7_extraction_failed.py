"""R7 when extraction failed: unevaluated lanes must not read as consistent.

Regression for the live UI bug (`evidence-consistent` while Voice and
SAM were `not_evaluated`). When corroboration is unavailable, R7 reads
the lane outcomes directly: uploaded-but-unevaluated lanes yield
`evidence-not-evaluated`, never `evidence-consistent`.
"""

from __future__ import annotations

from app.domain.enums import Verdict
from app.pipeline import policy
from app.pipeline.evidence import LaneOutcome, LaneStatus


def _r7(settings, *, voice_lane=None, sam_lane=None):
    _, rules = policy.evaluate_policy(
        settings, None, None, schema_ok=False,
        schema_errors=["Reader output failed schema validation"],
        voice_lane=voice_lane, sam_lane=sam_lane)
    by_id = {rule.rule_id: rule for rule in rules}
    return by_id["R7"], rules


def test_r7_failed_extraction_both_lanes_unevaluated(seeded_db, settings):
    voice = LaneOutcome(lane="voice", status=LaneStatus.NOT_EVALUATED,
                        detail="transcribed; comparison skipped")
    sam = LaneOutcome(lane="sam", status=LaneStatus.NOT_EVALUATED,
                      detail="delivery uploaded; vendor unresolved")
    r7, rules = _r7(settings, voice_lane=voice, sam_lane=sam)
    assert r7.passed is True  # no conflict found; policy meaning preserved
    assert r7.reason_code == "evidence-not-evaluated"
    assert "delivery" in r7.message and "voice" in r7.message
    assert "extraction failed" in r7.message
    verdict = policy.aggregate(rules)
    assert verdict == Verdict.DENY  # R8 still denies


def test_r7_failed_extraction_single_lane_named(seeded_db, settings):
    voice = LaneOutcome(lane="voice", status=LaneStatus.NOT_EVALUATED,
                        detail="comparison skipped")
    sam = LaneOutcome(lane="sam", status=LaneStatus.MISSING,
                      detail="no delivery evidence uploaded")
    r7, _ = _r7(settings, voice_lane=voice, sam_lane=sam)
    assert r7.reason_code == "evidence-not-evaluated"
    assert "voice" in r7.message
    assert "delivery" not in r7.message


def test_r7_failed_extraction_no_evidence_stays_consistent(seeded_db, settings):
    voice = LaneOutcome(lane="voice", status=LaneStatus.MISSING,
                        detail="no voice evidence uploaded")
    sam = LaneOutcome(lane="sam", status=LaneStatus.MISSING,
                      detail="no delivery evidence uploaded")
    r7, _ = _r7(settings, voice_lane=voice, sam_lane=sam)
    assert r7.reason_code == "evidence-consistent"


def test_r7_failed_extraction_failed_empty_count_as_unevaluated(seeded_db, settings):
    voice = LaneOutcome(lane="voice", status=LaneStatus.FAILED,
                        detail="transcription failed")
    sam = LaneOutcome(lane="sam", status=LaneStatus.EMPTY,
                      detail="empty stream")
    r7, _ = _r7(settings, voice_lane=voice, sam_lane=sam)
    assert r7.reason_code == "evidence-not-evaluated"


def test_r7_failed_extraction_no_lanes_backward_compat(seeded_db, settings):
    # Callers that do not pass lanes keep the old consistent result;
    # the pipeline always passes lanes, so live cases name them.
    r7, _ = _r7(settings)
    assert r7.reason_code == "evidence-consistent"
