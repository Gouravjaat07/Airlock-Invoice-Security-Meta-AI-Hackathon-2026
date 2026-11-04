"""Unit tests for media-quality metric definitions.

Hand-verified examples: WER/CER denominators and edit counts below
were computed by hand against the documented matching rules
(casefolded, whitespace-collapsed, standard Levenshtein).
"""

from app.evaluation.media_metrics import (
    char_error_rate,
    count_error,
    discrepancy_detected,
    mean_absolute_count_error,
    word_error_rate,
)


def test_wer_identical_is_zero():
    assert word_error_rate("Pay nine thousand now", "pay  nine THOUSAND now") == 0.0


def test_wer_counts_substitution_deletion_insertion():
    # 1 substitution ("mat"->"rug") over 6 reference words.
    assert word_error_rate("the cat sat on the rug",
                           "the cat sat on the mat") == 1 / 6
    # 1 deletion ("the") over 6 reference words.
    assert word_error_rate("the cat sat on mat",
                           "the cat sat on the mat") == 1 / 6
    # 1 insertion ("please") over 3 reference words.
    assert word_error_rate("please pay nine thousand",
                           "pay nine thousand") == 1 / 3


def test_wer_empty_reference_rules():
    assert word_error_rate("", "") == 0.0
    assert word_error_rate("   ", "") == 0.0
    assert word_error_rate("hello", "") is None


def test_cer_counts_char_edits():
    assert char_error_rate("abd", "abc") == 1 / 3
    assert char_error_rate("ABC", "abc") == 0.0
    assert char_error_rate("", "") == 0.0
    assert char_error_rate("x", "") is None


def test_count_error_and_mae():
    assert count_error(observed=5, expected=30) == -25
    assert count_error(observed=30, expected=30) == 0
    assert mean_absolute_count_error([(5, 30), (30, 30)]) == 12.5
    assert mean_absolute_count_error([]) is None


def test_discrepancy_rule_matches_corroboration_semantics():
    assert discrepancy_detected(observed=30, invoiced=30, tolerance=0) is False
    assert discrepancy_detected(observed=5, invoiced=30, tolerance=0) is True
    assert discrepancy_detected(observed=31, invoiced=30, tolerance=1) is False
    assert discrepancy_detected(observed=32, invoiced=30, tolerance=1) is True
