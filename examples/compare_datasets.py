"""Run from the repository root: uv run python examples/compare_datasets.py."""

from text2sql_eval.matching import MatchingConfig, compare_datasets

target = [[1, 100], [2, 200]]
generated = [[200, "Bob", 2], [100, "Ada", 1]]

# Default: either subset direction is allowed within rows and across datasets.
result = compare_datasets(target, generated)
print(result.model_dump_json(indent=2))

subset = compare_datasets([[1]], [[1], [2]])
assert subset.accepted
assert subset.relation == "target_subset"

# Require target values and a complete matching of equal row counts.
stricter = compare_datasets(
    target,
    generated,
    config=MatchingConfig(row_policy="target_subset", dataset_policy="equal"),
)
assert stricter.accepted
