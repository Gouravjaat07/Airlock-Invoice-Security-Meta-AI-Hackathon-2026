"""Media-quality metrics: WER/CER for transcription, count error for vision.

Pure functions, no I/O, no model calls. Two honest uses:

1. Unit-tested metric definitions ready for opt-in live evaluation
   (live voice/SAM quality is NOT_TESTED until the owner runs real
   providers over labelled audio/masks).
2. Offline fixture-consistency checks: mock adapters are fixture-driven
   by design, so scoring them against scenario ground truth measures
   fixture self-consistency, never model quality. Callers must label
   it exactly that way.

Matching rules: WER/CER use casefolded, whitespace-collapsed text and
standard Levenshtein edit distance ((S+D+I)/N against the reference).
Empty reference with empty hypothesis scores 0.0; empty reference with
non-empty hypothesis is undefined (None) rather than a fabricated 0.
"""

from __future__ import annotations


def _normalize(text: str) -> str:
    return " ".join(text.split()).casefold()


def _levenshtein(ref: list[str], hyp: list[str]) -> int:
    """Edit distance (insert/delete/substitute cost 1)."""
    previous = list(range(len(hyp) + 1))
    for i, ref_token in enumerate(ref, start=1):
        current = [i]
        for j, hyp_token in enumerate(hyp, start=1):
            cost = 0 if ref_token == hyp_token else 1
            current.append(min(previous[j] + 1,        # deletion
                               current[j - 1] + 1,     # insertion
                               previous[j - 1] + cost  # substitution
                               ))
        previous = current
    return previous[-1]


def word_error_rate(hypothesis: str, reference: str) -> float | None:
    """WER = edit distance over words / reference word count.

    Returns None when the reference has no words but the hypothesis
    does (undefined, not zero). Identical empties score 0.0.
    """
    ref_words = _normalize(reference).split()
    hyp_words = _normalize(hypothesis).split()
    if not ref_words:
        return 0.0 if not hyp_words else None
    return _levenshtein(ref_words, hyp_words) / len(ref_words)


def char_error_rate(hypothesis: str, reference: str) -> float | None:
    """CER = edit distance over characters / reference char count."""
    ref_chars = list(_normalize(reference))
    hyp_chars = list(_normalize(hypothesis))
    if not ref_chars:
        return 0.0 if not hyp_chars else None
    return _levenshtein(ref_chars, hyp_chars) / len(ref_chars)


def count_error(observed: int, expected: int) -> int:
    """Signed SAM-style count error (observed - expected)."""
    return observed - expected


def mean_absolute_count_error(pairs: list[tuple[int, int]]) -> float | None:
    """MAE over (observed, expected) count pairs; None when empty."""
    if not pairs:
        return None
    return sum(abs(observed - expected) for observed, expected in pairs) / len(pairs)


def discrepancy_detected(*, observed: int, invoiced: int,
                         tolerance: int) -> bool:
    """Deterministic count-comparison rule (mirrors corroboration).

    Kept as a one-line pure function so the benchmark can score the
    comparison rule itself against labelled (observed, invoiced,
    tolerance, expected_conflict) cases without running the pipeline.
    """
    return abs(observed - invoiced) > tolerance
