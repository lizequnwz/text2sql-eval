"""Aggregate scores without hiding unresolved cases or changing the denominator."""

from collections import Counter
from collections.abc import Sequence

from text2sql_eval.models import CaseScores, MetricName, MetricSummary

METRIC_NAMES: tuple[MetricName, ...] = (
    "row_count_match",
    "sampled_result_consistency",
    "sql_semantic",
)


def summarize(results: Sequence[CaseScores]) -> dict[MetricName, MetricSummary]:
    """Return confirmed passes / all supplied cases, and separate decision coverage.

    REVIEW and ERROR stay in the denominator but are not classified as SQL failures.
    An empty set has undefined rates, represented as None / JSON null.
    """
    results = [CaseScores.model_validate(result) for result in results]
    ids = [result.case_id for result in results]
    if len(ids) != len(set(ids)):
        raise ValueError("case_id must be unique when aggregating an evaluation.")
    total = len(results)
    summary = {}
    for name in METRIC_NAMES:
        counts = Counter(getattr(result, name).status for result in results)
        summary[name] = MetricSummary(
            cases=total,
            passed=counts["PASS"],
            failed=counts["FAIL"],
            review=counts["REVIEW"],
            errors=counts["ERROR"],
            pass_rate=counts["PASS"] / total if total else None,
            decision_coverage=(counts["PASS"] + counts["FAIL"]) / total if total else None,
        )
    return summary
