"""Reject inconsistent evidence before it can produce a misleading score."""

from __future__ import annotations

import pytest
from conftest import RecordingModel, decision
from pydantic import ValidationError

from text2sql_eval import CaseScores, Evaluator, JudgeDecision, QueryResult


@pytest.mark.parametrize(
    "overrides",
    [
        {"total_rows": None},
        {"total_rows": -1},
        {"total_rows": 0},
        {"total_rows": True},
        {"rows": [[1, 2]]},
        {"rows": [[float("nan")]]},
        {"rows": [[float("inf")]]},
        {"execution_error": "Query failed", "total_rows": 1},
        {"execution_error": "Query failed", "total_rows": None},
    ],
)
def test_rejects_inconsistent_success_or_error_evidence(overrides):
    values = {"columns": ["value"], "rows": [[1]], "total_rows": 1}
    values.update(overrides)
    with pytest.raises((ValidationError, ValueError)):
        QueryResult(**values)


def test_execution_failure_is_not_a_successful_empty_result():
    failed = QueryResult(columns=[], rows=[], total_rows=None, execution_error="Query failed")
    empty = QueryResult(columns=["customer_id"], rows=[], total_rows=0)
    assert failed.total_rows is None
    assert failed.execution_error
    assert empty.total_rows == 0
    assert empty.execution_error is None


def test_partial_previews_keep_the_known_total_count():
    result = QueryResult(columns=["customer_id"], rows=[[1], [2]], total_rows=2000)
    assert len(result.rows) == 2
    assert result.total_rows == 2000


def test_invalid_gold_is_not_silently_dropped_from_a_benchmark(make_case):
    with pytest.raises((ValidationError, ValueError)):
        make_case(
            target_result=QueryResult(
                columns=[], rows=[], total_rows=None, execution_error="Gold failed"
            )
        )


def test_empty_generated_sql_needs_an_explicit_failure(make_case):
    with pytest.raises((ValidationError, ValueError)):
        make_case(generated_sql="")


def test_judge_schema_requires_a_reason_and_review_flag():
    with pytest.raises(ValidationError):
        JudgeDecision(verdict="PASS", reason="Looks fine", evidence=[])
    with pytest.raises(ValidationError):
        JudgeDecision(verdict="PASS", reason="   ", needs_review=False, evidence=[])


def test_strict_judge_schema_has_no_implicit_fields_or_extra_properties():
    schema = JudgeDecision.model_json_schema()
    assert set(schema["required"]) == {"verdict", "reason", "needs_review", "evidence"}
    assert schema.get("additionalProperties") is False
    assert all("default" not in field for field in schema["properties"].values())


def test_saved_scores_round_trip_without_losing_review_state(make_case):
    result = Evaluator(RecordingModel(lambda _: decision(needs_review=True))).evaluate(make_case())
    restored = CaseScores.model_validate_json(result.model_dump_json())
    assert restored == result
    assert restored.row_count_match.score == 1
    assert restored.sampled_result_consistency.status == "REVIEW"
    assert restored.sampled_result_consistency.score is None


@pytest.mark.parametrize("tamper", ["score", "review_status"])
def test_saved_scores_reject_a_forged_confirmed_pass(make_case, tamper):
    result = Evaluator(RecordingModel(lambda _: decision(needs_review=True))).evaluate(make_case())
    record = result.model_dump(mode="json")
    metric = record["sampled_result_consistency"]
    if tamper == "score":
        metric["score"] = 1
    else:
        metric["status"] = "PASS"
        metric["score"] = 1
    with pytest.raises((ValidationError, ValueError)):
        CaseScores.model_validate(record)
