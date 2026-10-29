"""Build a report from fabricated cases and decisions, without invoking a model.

Run from the repository root:
    uv run python examples/html_report.py --output reports/demo.html
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from text2sql_eval import (
    CaseScores,
    EvaluationCase,
    JudgeDecision,
    JudgeMetadata,
    MetricName,
    MetricResult,
    MetricStatus,
    QueryResult,
    __version__,
    score_row_count,
    write_html_report,
)

TARGET_SQL = """SELECT customer_id, SUM(amount) AS total_sales
FROM orders
WHERE order_date >= DATE '2026-01-01'
  AND order_date < DATE '2026-02-01'
GROUP BY customer_id"""

SYNTHETIC_FINGERPRINT = hashlib.sha256(b"synthetic-demo-no-model-called-v1").hexdigest()


def _metric(
    name: MetricName,
    status: MetricStatus,
    reason: str,
    evidence: list[str],
) -> MetricResult:
    """Create a canned response with valid status/review invariants."""
    metadata = JudgeMetadata(
        model="synthetic-demo/no-model-called",
        prompt_sha256=SYNTHETIC_FINGERPRINT,
        elapsed_seconds=0.0,
        token_usage=None,
    )
    if status == "ERROR":
        return MetricResult(
            name=name,
            status=status,
            reason=f"Synthetic example: {reason}",
            metadata=metadata,
            error_type="SyntheticError",
        )
    decision = JudgeDecision(
        verdict="FAIL" if status == "FAIL" else "PASS",
        reason=f"Synthetic example: {reason}",
        needs_review=status == "REVIEW",
        evidence=evidence,
    )
    return MetricResult(
        name=name,
        status=status,
        reason=decision.reason,
        judgment=decision,
        metadata=metadata,
    )


def _result(rows: list[list], *, total_rows: int | None = None) -> QueryResult:
    return QueryResult(
        columns=["customer_id", "total_sales"],
        rows=rows,
        total_rows=len(rows) if total_rows is None else total_rows,
    )


def build_demo() -> tuple[list[EvaluationCase], list[CaseScores]]:
    """Return 36 synthetic cases spanning the report's evidence and status states."""
    cases: list[EvaluationCase] = []
    results: list[CaseScores] = []
    labels = (
        "Matching customer totals",
        "Supplementary customer names",
        "Truncated output",
        "Same preview, missing date filter",
        "Incorrect amount",
        "Missing customer",
        "Empty result",
        "Execution error",
        "Judge error and uncertain ties",
    )

    for index in range(36):
        scenario = index % len(labels)
        case_id = f"synthetic-{index + 1:03d}"
        target = _result([[1, 100], [2, 200], [3, 300]])
        generated = _result([[1, 100], [2, 200], [3, 300]])
        target_sql = TARGET_SQL
        generated_sql = TARGET_SQL
        question = "What is the total sales amount for each customer in January 2026?"
        context = (
            f"Fabricated report fixture: {labels[scenario]}. Neither SQL statement was executed. "
            "Customer IDs are unique, and each order belongs to a customer. "
            "No final display order is required unless the question states otherwise."
        )
        sampled_status: MetricStatus = "PASS"
        semantic_status: MetricStatus = "PASS"
        sampled_reason = "The supplied customer totals agree."
        semantic_reason = "The SQL preserves the requested January filter and customer grain."
        sampled_evidence = ["customer_id 1 has total_sales 100 in both supplied previews."]
        semantic_evidence = ["Both SQL statements filter January and group by customer_id."]

        if scenario == 1:
            generated = QueryResult(
                columns=["customer_id", "customer_name", "total_sales"],
                rows=[[3, "Cleo", 300], [2, "Bob", 200], [1, "Ada", 100]],
                total_rows=3,
            )
            generated_sql = """SELECT o.customer_id, c.customer_name, SUM(o.amount) AS total_sales
FROM orders o
JOIN customers c ON c.customer_id = o.customer_id
WHERE o.order_date >= DATE '2026-01-01'
  AND o.order_date < DATE '2026-02-01'
GROUP BY o.customer_id, c.customer_name
ORDER BY total_sales DESC"""
            context += " Every order has a matching customer; customer_name is supplementary."
            sampled_reason = "The extra name column and reversed display order preserve totals."
            semantic_reason = "The stated unique customer join preserves aggregation grain."
            sampled_evidence = ["customer_id 1 still has total_sales 100; Ada is extra context."]
            semantic_evidence = ["The January filter remains; the final ORDER BY is incidental."]
        elif scenario == 2:
            rows = [[number, number * 10] for number in range(1, 81)]
            target = _result(rows, total_rows=1200)
            generated = _result(rows, total_rows=1200)
            sampled_reason = "The first 50 rows agree; unseen rows remain outside this metric."
            sampled_evidence = ["1,200 total rows; at most 50 are embedded per query."]
        elif scenario == 3:
            generated_sql = """SELECT customer_id, SUM(amount) AS total_sales
FROM orders
GROUP BY customer_id"""
            semantic_status = "FAIL"
            context += " The fabricated snapshot contains only January orders."
            sampled_reason = "The fabricated preview agrees on this snapshot."
            semantic_reason = "Generated SQL omits the date range required by the question."
            semantic_evidence = ["The generated SQL has no WHERE clause for January 2026."]
        elif scenario == 4:
            generated = _result([[1, 100], [2, 999], [3, 300]])
            generated_sql = TARGET_SQL.replace("SUM(amount)", "SUM(amount + 1)")
            sampled_status = "FAIL"
            semantic_status = "FAIL"
            sampled_reason = "The same customer's observed amount differs."
            semantic_reason = "Adding one to every order changes the requested total."
            sampled_evidence = ["customer_id 2: target 200; generated 999."]
            semantic_evidence = ["SUM(amount + 1) differs from SUM(amount)."]
        elif scenario == 5:
            generated = _result([[1, 100], [2, 200]])
            generated_sql = TARGET_SQL + "\nHAVING SUM(amount) < 300"
            sampled_status = "FAIL"
            semantic_status = "FAIL"
            sampled_reason = "The complete three-row target includes customer 3, which is missing."
            semantic_reason = "The extra HAVING condition excludes a requested customer."
            sampled_evidence = ["Target count 3; generated count 2; customer 3 is absent."]
            semantic_evidence = ["HAVING SUM(amount) < 300 is not requested."]
        elif scenario == 6:
            target = _result([])
            generated = _result([])
            context += " The fabricated input has no January orders."
            sampled_reason = "Both complete outputs are empty; no sample contradiction is shown."
            sampled_evidence = ["Both total_rows values are 0, with no preview rows."]
        elif scenario == 7:
            generated_sql = TARGET_SQL.replace("SUM(amount)", "SUM(missing_amount)")
            generated = QueryResult(
                columns=[],
                rows=[],
                total_rows=None,
                execution_error="Synthetic execution failure: missing_amount is not a column.",
            )
            sampled_status = "ERROR"
            semantic_status = "FAIL"
            context += " orders has amount; it has no missing_amount column."
            sampled_reason = "The fabricated generated execution failed, so no result is compared."
            semantic_reason = (
                "The generated query refers to a column absent from the stated schema."
            )
            sampled_evidence = []
            semantic_evidence = ["SUM(missing_amount) references an undefined column."]
        elif scenario == 8:
            question = "Which 50 customers had the highest sales in January 2026?"
            target = _result([[number, 100] for number in range(1, 51)], total_rows=50)
            generated = _result([[number, 100] for number in range(2, 52)], total_rows=50)
            generated_sql = TARGET_SQL + "\nORDER BY total_sales DESC LIMIT 50"
            target_sql = generated_sql
            sampled_status = "ERROR"
            semantic_status = "REVIEW"
            sampled_reason = "A fabricated provider error prevented the sampled judgment."
            semantic_reason = "The question does not define how to choose boundary ties."
            sampled_evidence = []
            semantic_evidence = ["ORDER BY total_sales DESC LIMIT 50 has no unique tie-break key."]
        case = EvaluationCase(
            case_id=case_id,
            question=question,
            target_sql=target_sql,
            generated_sql=generated_sql,
            target_result=target,
            generated_result=generated,
            dialect="postgresql",
            context=context,
        )
        cases.append(case)
        results.append(
            CaseScores(
                case_id=case_id,
                row_count_match=score_row_count(case),
                sampled_result_consistency=_metric(
                    "sampled_result_consistency",
                    sampled_status,
                    sampled_reason,
                    sampled_evidence,
                ),
                sql_semantic=_metric(
                    "sql_semantic", semantic_status, semantic_reason, semantic_evidence
                ),
            )
        )
    return cases, results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("reports/demo.html"))
    args = parser.parse_args()
    cases, results = build_demo()
    path = write_html_report(
        cases,
        results,
        args.output,
        package_version=__version__,
        title="Synthetic demo · Text-to-SQL evaluation",
    )
    print(f"Wrote 36 synthetic cases and canned decisions to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
