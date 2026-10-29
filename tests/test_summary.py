"""Unresolved and failed cases must remain visible in fixed-denominator reports."""

from __future__ import annotations

import pytest
from conftest import RecordingModel, decision

from text2sql_eval import Evaluator, summarize


def test_summary_does_not_inflate_rates_by_dropping_review_or_error_cases(make_case):
    responses = iter(
        [
            decision("PASS"),
            decision("PASS"),
            decision("FAIL"),
            decision("FAIL"),
            decision(needs_review=True),
            decision(needs_review=True),
            RuntimeError("Provider unavailable"),
            RuntimeError("Provider unavailable"),
        ]
    )
    evaluator = Evaluator(RecordingModel(lambda messages: next(responses)))
    cases = [make_case(case_id=f"case-{index}") for index in range(4)]
    summaries = summarize(evaluator.evaluate_many(cases))
    for key in ("sampled_result_consistency", "sql_semantic"):
        metric = summaries[key]
        assert metric.cases == 4
        assert metric.passed == 1
        assert metric.failed == 1
        assert metric.review == 1
        assert metric.errors == 1
        assert metric.pass_rate == pytest.approx(0.25)
        assert metric.decision_coverage == pytest.approx(0.5)
    assert summaries["row_count_match"].pass_rate == 1


def test_empty_summary_does_not_claim_zero_or_perfect_accuracy():
    summaries = summarize([])
    assert set(summaries) == {
        "row_count_match",
        "sampled_result_consistency",
        "sql_semantic",
    }
    for metric in summaries.values():
        assert metric.cases == 0
        assert metric.pass_rate is None
        assert metric.decision_coverage is None


def test_duplicate_score_ids_cannot_count_the_same_question_twice(make_case):
    score = Evaluator(RecordingModel()).evaluate(make_case())
    with pytest.raises(ValueError):
        summarize([score, score])


def test_summary_cannot_turn_a_mutated_review_into_a_confirmed_pass(make_case):
    result = Evaluator(RecordingModel(lambda _: decision(needs_review=True))).evaluate(make_case())
    result.sampled_result_consistency.status = "PASS"
    result.sampled_result_consistency.score = 1
    with pytest.raises(ValueError):
        summarize([result])
