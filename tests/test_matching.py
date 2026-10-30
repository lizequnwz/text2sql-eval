"""Exercise value containment and occurrence matching against independent examples."""

from __future__ import annotations

import random
from collections import Counter
from datetime import date, datetime
from decimal import Decimal

import pytest

from text2sql_eval import QueryResult
from text2sql_eval.matching import MatchingConfig, compare_datasets, compare_rows

POLICIES = ("equal", "target_subset", "generated_subset", "bidirectional")


def allowed_pair(target, generated, policy):
    """Small string-only oracle, deliberately independent of the production matcher."""
    left, right = Counter(target), Counter(generated)
    if policy == "equal":
        return left == right
    if policy == "target_subset":
        return left <= right
    if policy == "generated_subset":
        return right <= left
    return left <= right or right <= left


def brute_force_count(target, generated, policy):
    def search(index, used):
        if index == len(target):
            return 0
        best = search(index + 1, used)
        for candidate, row in enumerate(generated):
            if candidate not in used and allowed_pair(target[index], row, policy):
                best = max(best, 1 + search(index + 1, used | {candidate}))
        return best

    return search(0, set())


@pytest.mark.parametrize(
    ("target", "generated", "relation"),
    [
        (["Alice", 30], [30, "Alice"], "equal"),
        (["Alice", 30], [30, "Alice", "NY"], "target_subset"),
        (["Alice", 30, "NY"], [30, "Alice"], "generated_subset"),
        (["Alice", 30], ["Bob", 30], "incompatible"),
        ([1, 1], [1, 999], "incompatible"),
    ],
)
def test_row_comparison_reports_actual_direction(target, generated, relation):
    result = compare_rows(target, generated)
    assert result.relation == relation
    assert result.accepted is (relation != "incompatible")
    assert result.target_value_count == len(target)
    assert result.generated_value_count == len(generated)


@pytest.mark.parametrize("policy", POLICIES)
def test_row_policy_controls_acceptance_without_hiding_observed_direction(policy):
    result = compare_rows(["Alice", 30], ["Alice"], policy=policy)
    assert result.relation == "generated_subset"
    assert result.accepted is (policy in {"generated_subset", "bidirectional"})


def test_default_accepts_omitted_values_as_requested_without_essential_field_rules():
    result = compare_datasets([[1, 100], [2, 200]], [[2], [1]])
    assert result.accepted
    assert result.relation == "full_match"
    assert result.matched_row_count == 2
    assert result.row_relation_counts.get("generated_subset") == 2
    assert result.row_count_match


@pytest.mark.parametrize(
    ("target", "generated", "relation"),
    [
        ([["A"], ["B"]], [["A"]], "generated_subset"),
        ([["A"]], [["A"], ["B"]], "target_subset"),
    ],
)
def test_default_accepts_either_dataset_subset_and_equal_policy_can_reject_it(
    target, generated, relation
):
    result = compare_datasets(target, generated)
    assert result.accepted
    assert result.relation == relation
    assert result.config.row_policy == "bidirectional"
    assert result.config.dataset_policy == "bidirectional"
    assert not result.row_count_match
    strict = compare_datasets(target, generated, config=MatchingConfig(dataset_policy="equal"))
    assert not strict.accepted
    assert strict.relation == relation


def test_directed_row_policy_can_reject_the_same_missing_measure():
    result = compare_datasets(
        [[1, 100], [2, 200]],
        [[2], [1]],
        config=MatchingConfig(row_policy="target_subset"),
    )
    assert not result.accepted
    assert result.matched_row_count == 0
    assert result.unmatched_target_indices == [0, 1]
    assert result.unmatched_generated_indices == [0, 1]


def test_column_and_row_order_do_not_change_matching_or_inputs():
    target = [["Alice", 100], ["Bob", 200]]
    generated = [[200, "Bob", "LA"], [100, "Alice", "NY"]]
    result = compare_datasets(target, generated)
    assert result.accepted
    assert result.matched_row_count == 2
    assert result.target_coverage == result.generated_coverage == result.f1 == 1
    assert {(item.target_index, item.generated_index) for item in result.matches} == {
        (0, 1),
        (1, 0),
    }
    assert target == [["Alice", 100], ["Bob", 200]]
    assert generated == [[200, "Bob", "LA"], [100, "Alice", "NY"]]


def test_repeated_rows_do_not_reuse_a_generated_occurrence():
    result = compare_datasets([["A"], ["A"], ["B"]], [["A"], ["B"], ["B"]])
    assert not result.accepted
    assert result.row_count_match
    assert result.matched_row_count == 2
    assert len(result.unmatched_target_indices) == len(result.unmatched_generated_indices) == 1
    assert result.f1 == pytest.approx(2 / 3)
    assert len({item.target_index for item in result.matches}) == 2
    assert len({item.generated_index for item in result.matches}) == 2


def test_maximum_matching_avoids_the_greedy_choice_that_loses_a_match():
    # A can match either generated row; B can match only the first.
    result = compare_datasets([["A"], ["B"]], [["A", "B"], ["A", "C"]])
    assert result.accepted
    assert result.matched_row_count == 2
    assert {(item.target_index, item.generated_index) for item in result.matches} == {
        (0, 1),
        (1, 0),
    }


def test_many_duplicate_rows_match_without_a_quadratic_occurrence_graph():
    target = [["A"] for _ in range(10_000)]
    generated = [["extra", "A"] for _ in range(10_000)]
    result = compare_datasets(target, generated, config=MatchingConfig(max_candidate_edges=10))
    assert result.accepted
    assert result.matched_row_count == 10_000
    assert len({item.generated_index for item in result.matches}) == 10_000


@pytest.mark.parametrize("policy", POLICIES)
def test_dataset_policy_decides_whether_extra_generated_records_are_accepted(policy):
    result = compare_datasets([["A"]], [["A"], ["B"]], config=MatchingConfig(dataset_policy=policy))
    assert result.relation == "target_subset"
    assert result.accepted is (policy in {"target_subset", "bidirectional"})
    assert not result.row_count_match
    assert result.target_coverage == 1
    assert result.generated_coverage == 0.5
    assert result.f1 == pytest.approx(2 / 3)


@pytest.mark.parametrize("policy", POLICIES)
def test_dataset_policy_decides_whether_missing_reference_records_are_accepted(policy):
    result = compare_datasets([["A"], ["B"]], [["A"]], config=MatchingConfig(dataset_policy=policy))
    assert result.relation == "generated_subset"
    assert result.accepted is (policy in {"generated_subset", "bidirectional"})
    assert result.target_coverage == 0.5
    assert result.generated_coverage == 1


def test_partial_overlap_keeps_missing_and_extra_records_visible():
    result = compare_datasets([["A"], ["B"]], [["B"], ["C"]])
    assert not result.accepted
    assert result.relation == "partial_overlap"
    assert result.matched_row_count == 1
    assert result.target_coverage == result.generated_coverage == result.f1 == 0.5


@pytest.mark.parametrize("policy", POLICIES)
def test_empty_complete_results_agree_without_dividing_by_zero(policy):
    result = compare_datasets([], [], config=MatchingConfig(dataset_policy=policy))
    assert result.accepted
    assert result.relation == "full_match"
    assert result.target_coverage is None
    assert result.generated_coverage is None
    assert result.f1 == 1
    assert result.matches == []


def test_empty_target_is_a_vacuous_subset_by_default_and_strict_equal_rejects_it():
    assert compare_datasets([], [["A"]]).accepted
    assert compare_datasets([["A"]], []).accepted
    assert not compare_datasets([], [["A"]], config=MatchingConfig(dataset_policy="equal")).accepted
    result = compare_datasets([], [["A"]], config=MatchingConfig(dataset_policy="target_subset"))
    assert result.accepted
    assert result.relation == "target_subset"
    assert result.target_coverage is None
    assert result.generated_coverage == 0
    assert result.f1 == 0


@pytest.mark.parametrize(
    ("left", "right", "accepted"),
    [
        (1, 1.0, True),
        (Decimal("1.00"), 1, True),
        (Decimal("0.1"), 0.1, True),
        (True, 1, False),
        ("1", 1, False),
        (None, "", False),
        (None, 0, False),
        (None, float("nan"), True),
        ("Alice", "alice", False),
        ("Alice", " Alice ", False),
        (0.1 + 0.2, 0.3, False),
        (date(2026, 1, 1), date(2026, 1, 1), True),
        (date(2026, 1, 1), "2026-01-01", False),
        (datetime(2026, 1, 1, 12), datetime(2026, 1, 1, 12), True),
        (b"Alice", "Alice", False),
        ([1, 2], [2, 1], False),
        ({"a": 1, "b": [2, 3]}, {"b": [2, 3], "a": 1}, True),
    ],
)
def test_cell_normalization_is_explicit_and_does_not_discard_type_or_structure(
    left, right, accepted
):
    assert compare_rows([left], [right]).accepted is accepted


@pytest.mark.parametrize("value", [float("inf"), float("-inf"), Decimal("Infinity"), object()])
def test_uncomparable_cells_raise_instead_of_becoming_a_false_decision(value):
    with pytest.raises((TypeError, ValueError)):
        compare_rows([value], [value])


@pytest.mark.parametrize(
    "dataset",
    [
        [[1], [2, 3]],
        [{"a": 1}, {"b": 2}],
        {"columns": ["a", "b"], "rows": [[1]]},
        "not a row dataset",
        [1, 2, 3],
    ],
)
def test_invalid_dataset_shapes_are_rejected(dataset):
    with pytest.raises((TypeError, ValueError)):
        compare_datasets(dataset, [[1]])


def test_records_and_labeled_result_objects_ignore_labels_and_column_order():
    result = compare_datasets(
        [{"id": 1, "amount": 100}, {"id": 2, "amount": 200}],
        {"columns": ["amount", "id"], "rows": [[200, 2], [100, 1]], "total_rows": 2},
    )
    assert result.accepted


def test_complete_query_results_are_supported_and_previews_are_rejected():
    complete = QueryResult(columns=["id"], rows=[[1]], total_rows=1)
    assert compare_datasets(complete, [[1]]).accepted
    preview = QueryResult(columns=["id"], rows=[[1]], total_rows=2)
    with pytest.raises(ValueError):
        compare_datasets(preview, [[1]])
    with pytest.raises(ValueError):
        compare_datasets({"columns": ["id"], "rows": [[1]], "total_rows": 2}, [[1]])


def test_failed_query_is_not_compared_as_an_empty_result():
    failed = QueryResult(columns=[], rows=[], total_rows=None, execution_error="Execution failed")
    with pytest.raises(ValueError):
        compare_datasets(failed, [])


def test_pandas_frames_preserve_duplicate_labels_ignore_index_and_handle_missing_values():
    pd = pytest.importorskip("pandas")
    target = pd.DataFrame([[1, pd.NA], [2, pd.NaT]], columns=["duplicate", "duplicate"])
    generated = pd.DataFrame([[None, 2.0], [float("nan"), 1.0]], index=[8, 9])
    result = compare_datasets(target, generated)
    assert result.accepted
    assert result.matched_row_count == 2


def test_zero_column_dataframe_preserves_its_row_occurrences():
    pd = pytest.importorskip("pandas")
    frame = pd.DataFrame(index=[10, 20])
    result = compare_datasets(frame, [[], []])
    assert result.accepted
    assert result.target_row_count == result.generated_row_count == 2
    assert result.matched_row_count == 2


def test_pandas_subclass_and_scalar_sentinels_are_supported():
    pd = pytest.importorskip("pandas")

    class ReportFrame(pd.DataFrame):
        pass

    frame = ReportFrame([[pd.NA, pd.Timestamp("2026-01-01")]])
    result = compare_datasets(frame, [[None, datetime(2026, 1, 1)]])
    assert result.accepted
    assert compare_rows([pd.NaT], [None]).accepted


def test_numpy_scalar_normalization_preserves_null_numeric_and_boolean_roles():
    np = pytest.importorskip("numpy")
    result = compare_datasets(
        [[np.int64(1), np.float64("nan"), np.bool_(True), np.datetime64("NaT", "ns")]],
        [[None, True, None, 1.0]],
    )
    assert result.accepted
    assert not compare_rows([np.bool_(True)], [np.int64(1)]).accepted


def test_dense_candidate_limit_raises_instead_of_silently_truncating_the_matching():
    with pytest.raises(ValueError):
        compare_datasets(
            [["A"], ["B"]],
            [["A", "B"], ["A", "C"]],
            config=MatchingConfig(max_candidate_edges=1),
        )


def test_small_random_problems_agree_with_an_exhaustive_one_to_one_oracle():
    rng = random.Random(62026)
    for _ in range(80):
        left_width, right_width = rng.choice([1, 2]), rng.choice([1, 2])
        target = [rng.choices("ABC", k=left_width) for _ in range(rng.randrange(4))]
        generated = [rng.choices("ABC", k=right_width) for _ in range(rng.randrange(4))]
        for policy in POLICIES:
            expected = brute_force_count(target, generated, policy)
            result = compare_datasets(
                target,
                generated,
                config=MatchingConfig(row_policy=policy, dataset_policy="equal"),
            )
            assert result.matched_row_count == expected, (target, generated, policy)
            assert result.accepted is (expected == len(target) == len(generated))
            assert len(result.matches) == expected
            assert len({item.target_index for item in result.matches}) == expected
            assert len({item.generated_index for item in result.matches}) == expected
            assert all(
                allowed_pair(target[item.target_index], generated[item.generated_index], policy)
                for item in result.matches
            )


def test_row_permutations_preserve_scores_and_repeated_runs_preserve_alignment():
    target = [["A"], ["B"], ["A"]]
    generated = [["A", "B"], ["A", "C"], ["A", "D"]]
    original = compare_datasets(target, generated)
    repeated = compare_datasets(target, generated)
    permuted = compare_datasets(target[::-1], generated[::-1])
    assert original.model_dump() == repeated.model_dump()
    assert original.matched_row_count == permuted.matched_row_count
    assert original.f1 == permuted.f1
    assert original.accepted == permuted.accepted


@pytest.mark.parametrize(
    "options",
    [
        {"row_policy": "unknown"},
        {"dataset_policy": "unknown"},
        {"max_candidate_edges": 0},
        {"max_candidate_edges": -1},
        {"max_candidate_edges": True},
    ],
)
def test_invalid_configuration_is_rejected(options):
    with pytest.raises((TypeError, ValueError)):
        MatchingConfig(**options)
