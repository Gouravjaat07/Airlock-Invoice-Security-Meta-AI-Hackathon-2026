"""Phase 5 extraction scoring: normalized field comparison."""

import phase5_eval as evaluation

EXPECTED = {
    "vendor_name": "Acme Supplies Ltd",
    "invoice_number": "INV-2026-0042",
    "issue_date": "2026-09-01",
    "due_date": "2026-10-01",
    "currency": "USD",
    "subtotal": "1000.00",
    "tax": "200.00",
    "total": "1200.00",
    "bank_reference": "GB29 NWBK 6016 1331 9268 19",
    "po_reference": "PO-7781",
    "line_items": [
        {"description": "Widget A", "quantity": "10", "unit_price": "100.00"},
    ],
}


def test_exact_match_scores_complete():
    score = evaluation.score_extraction(dict(EXPECTED), EXPECTED)
    assert score["complete_match"] is True
    assert score["accuracy"] == 1.0
    assert score["hits"] == score["total"]


def test_text_normalization_ignores_case_and_whitespace():
    predicted = dict(EXPECTED, vendor_name="  acme   supplies ltd ",
                     invoice_number="inv-2026-0042")
    score = evaluation.score_extraction(predicted, EXPECTED)
    assert score["fields"]["vendor_name"] is True
    assert score["fields"]["invoice_number"] is True
    assert score["complete_match"] is True


def test_money_comparison_is_decimal_strict():
    assert evaluation.score_extraction(
        dict(EXPECTED, total="1200.00"), EXPECTED)["fields"]["total"] is True
    assert evaluation.score_extraction(
        dict(EXPECTED, total="1200.0"), EXPECTED)["fields"]["total"] is True
    assert evaluation.score_extraction(
        dict(EXPECTED, total="1200.01"),
        EXPECTED)["complete_match"] is False
    assert evaluation.score_extraction(
        dict(EXPECTED, total="not-a-number"),
        EXPECTED)["fields"]["total"] is False


def test_wrong_vendor_breaks_complete_match():
    score = evaluation.score_extraction(
        dict(EXPECTED, vendor_name="Someone Else"), EXPECTED)
    assert score["fields"]["vendor_name"] is False
    assert score["complete_match"] is False
    assert score["accuracy"] < 1.0


def test_line_item_mismatch_detected():
    predicted = dict(EXPECTED, line_items=[
        {"description": "Widget A", "quantity": "9", "unit_price": "100.00"},
    ])
    score = evaluation.score_extraction(predicted, EXPECTED)
    assert score["fields"]["line_item_count"] is True
    assert score["fields"]["line_items_exact"] is False
    assert score["complete_match"] is False


def test_missing_optional_references_score_false_not_crash():
    predicted = dict(EXPECTED)
    predicted.pop("po_reference")
    predicted["bank_reference"] = None
    score = evaluation.score_extraction(predicted, EXPECTED)
    assert score["fields"]["po_reference"] is False
    assert score["fields"]["bank_reference"] is False


def test_partial_live_flags_rejected():
    assert evaluation.main(["--live"]) == 2
    assert evaluation.main(["--allow-billable"]) == 2
