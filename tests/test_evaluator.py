"""Exercise routing, uncertainty, failure isolation, and judge independence offline."""

from __future__ import annotations

import asyncio
import hashlib

import pytest
from conftest import RecordingModel, decision, payload

from text2sql_eval import Evaluator, JudgeDecision, QueryResult, score_row_count
from text2sql_eval import prompts as prompt_module


def test_row_count_is_not_mistaken_for_value_correctness(make_case):
    case = make_case(
        target_result=QueryResult(columns=["count"], rows=[[100]], total_rows=1),
        generated_result=QueryResult(columns=["count"], rows=[[999]], total_rows=1),
    )
    result = score_row_count(case)
    assert result.status == "PASS"
    assert result.score == 1


def test_row_count_uses_complete_counts_not_preview_lengths(make_case):
    case = make_case(
        target_result=QueryResult(columns=["id"], rows=[[1]], total_rows=1000),
        generated_result=QueryResult(columns=["id"], rows=[[1]], total_rows=999),
    )
    assert score_row_count(case).status == "FAIL"


def test_uses_explicit_strict_pydantic_output(make_case):
    model = RecordingModel()
    Evaluator(model).evaluate(make_case())
    assert model.bindings
    for schema, options in model.bindings:
        assert schema is JudgeDecision
        assert options["method"] == "json_schema"
        assert options["strict"] is True
        assert options["include_raw"] is True
    assert len(model.calls) == 2


@pytest.mark.parametrize("provisional_verdict", ["PASS", "FAIL"])
def test_review_flag_never_becomes_a_confirmed_pass_or_error_flag(make_case, provisional_verdict):
    model = RecordingModel(
        lambda messages: decision(
            provisional_verdict,
            needs_review=True,
            reason="The disjoint previews do not establish whether unseen tied rows agree.",
        )
    )
    result = Evaluator(model).evaluate(make_case())
    for metric in (result.sampled_result_consistency, result.sql_semantic):
        assert metric.status == "REVIEW"
        assert metric.score is None
        assert metric.judgment.needs_review is True
    assert result.row_count_match.status == "PASS"


def test_one_provider_failure_does_not_hide_the_other_judgment(make_case):
    responses = iter([RuntimeError("Connection unavailable"), decision("FAIL")])
    model = RecordingModel(lambda messages: next(responses))
    result = Evaluator(model).evaluate(make_case())
    assert result.sampled_result_consistency.status == "ERROR"
    assert result.sampled_result_consistency.score is None
    assert result.sql_semantic.status == "FAIL"
    assert len(model.calls) == 2


@pytest.mark.parametrize(
    "response",
    [
        {"parsed": None, "raw": None, "parsing_error": ValueError("Malformed output")},
        {"parsed": None, "raw": None, "parsing_error": None},
    ],
)
def test_unparseable_or_refused_output_is_an_error_not_a_sql_failure(make_case, response):
    model = RecordingModel(lambda messages: response)
    result = Evaluator(model).evaluate(make_case())
    assert result.sampled_result_consistency.status == "ERROR"
    assert result.sql_semantic.status == "ERROR"
    assert result.sampled_result_consistency.score is None


def test_failed_execution_is_not_compared_as_an_empty_table(make_case):
    model = RecordingModel()
    case = make_case(
        generated_result=QueryResult(
            columns=[], rows=[], total_rows=None, execution_error="Column does not exist"
        )
    )
    result = Evaluator(model).evaluate(case)
    assert result.row_count_match.status == "ERROR"
    assert result.sampled_result_consistency.status == "ERROR"
    assert result.sql_semantic.status == "PASS"
    assert len(model.calls) == 1
    assert "target_result" not in payload(model.calls[0])


def test_missing_generated_sql_produces_visible_errors_without_paid_calls(make_case):
    model = RecordingModel()
    case = make_case(
        generated_sql="",
        generated_result=QueryResult(
            columns=[], rows=[], total_rows=None, execution_error="SQL generation failed"
        ),
    )
    result = Evaluator(model).evaluate(case)
    assert result.row_count_match.status == "ERROR"
    assert result.sampled_result_consistency.status == "ERROR"
    assert result.sql_semantic.status == "ERROR"
    assert model.calls == []


def test_sql_judge_is_not_anchored_by_results_or_the_other_judge(make_case):
    secret = "PREVIEW_ONLY_SENTINEL_481"
    model = RecordingModel()
    case = make_case(
        target_result=QueryResult(columns=["value"], rows=[[secret]], total_rows=731),
        generated_result=QueryResult(columns=["value"], rows=[[secret]], total_rows=731),
    )
    Evaluator(model).evaluate(case)
    sampled, semantic = [payload(messages) for messages in model.calls]
    assert "target_result" in sampled
    assert "generated_result" in sampled
    assert "target_result" not in semantic
    assert "generated_result" not in semantic
    assert secret not in str(semantic)
    assert "total_rows" not in str(semantic)
    assert "verdict" not in semantic
    assert semantic["question"] == case.question
    assert semantic["target_sql"] == case.target_sql
    assert semantic["generated_sql"] == case.generated_sql


def test_preview_limit_is_enforced_without_claiming_full_coverage(make_case):
    model = RecordingModel()
    rows = [[number] for number in range(80)]
    case = make_case(
        target_result=QueryResult(columns=["id"], rows=rows, total_rows=1000),
        generated_result=QueryResult(columns=["id"], rows=rows, total_rows=1000),
    )
    Evaluator(model).evaluate(case)
    preview = payload(model.calls[0])
    for key in ("target_result", "generated_result"):
        assert len(preview[key]["rows"]) == 50
        assert preview[key]["rows"] == rows[:50]
        assert preview[key]["total_rows"] == 1000
        assert preview[key]["truncated"] is True
    assert len(case.target_result.rows) == 80


def test_duplicate_case_ids_are_rejected_before_any_judge_call(make_case):
    model = RecordingModel()
    case = make_case()
    with pytest.raises(ValueError):
        Evaluator(model).evaluate_many([case, case])
    assert model.calls == []


def test_async_batches_preserve_input_order_despite_completion_order(make_case):
    async def respond(messages):
        question = payload(messages)["question"]
        await asyncio.sleep(0.01 if "slow" in question else 0)
        return decision()

    model = RecordingModel(respond)
    cases = [
        make_case(case_id="slow", question="Return slow customer totals."),
        make_case(case_id="fast", question="Return fast customer totals."),
    ]
    results = asyncio.run(Evaluator(model).aevaluate_many(cases, concurrency=2))
    assert [result.case_id for result in results] == ["slow", "fast"]
    assert all(result.sql_semantic.status == "PASS" for result in results)
    assert len(model.calls) == 4


@pytest.mark.parametrize("asynchronous", [False, True])
def test_mutated_input_is_rejected_before_either_judge_runs(make_case, asynchronous):
    model = RecordingModel()
    evaluator = Evaluator(model)
    case = make_case()
    case.generated_result.rows[0][0] = float("nan")
    with pytest.raises(ValueError):
        if asynchronous:
            asyncio.run(evaluator.aevaluate(case))
        else:
            evaluator.evaluate(case)
    assert model.calls == []


def test_row_count_revalidates_a_mutated_count(make_case):
    case = make_case()
    case.generated_result.total_rows = -1
    with pytest.raises(ValueError):
        score_row_count(case)


@pytest.mark.parametrize("asynchronous", [False, True])
def test_batches_validate_every_case_before_making_requests(make_case, asynchronous):
    model = RecordingModel()
    evaluator = Evaluator(model)
    first = make_case(case_id="valid")
    last = make_case(case_id="mutated")
    last.generated_result.rows.append([3])
    with pytest.raises(ValueError):
        if asynchronous:
            asyncio.run(evaluator.aevaluate_many([first, last]))
        else:
            evaluator.evaluate_many([first, last])
    assert model.calls == []


def test_fingerprint_identifies_the_actual_prompt_sent_to_each_judge(make_case, monkeypatch):
    model = RecordingModel()
    evaluator = Evaluator(model)
    monkeypatch.setattr(prompt_module, "system_prompt", lambda metric: "CHANGED AFTER CONSTRUCTION")
    result = evaluator.evaluate(make_case())
    for messages, metric in zip(
        model.calls, [result.sampled_result_consistency, result.sql_semantic], strict=True
    ):
        actual = messages[0].content
        assert actual != "CHANGED AFTER CONSTRUCTION"
        assert metric.metadata.prompt_sha256 == hashlib.sha256(actual.encode("utf-8")).hexdigest()
