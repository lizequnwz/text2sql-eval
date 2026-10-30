"""Three explicit scores for pre-executed text-to-SQL predictions."""

from text2sql_eval._version import __version__
from text2sql_eval.evaluator import Evaluator, score_row_count
from text2sql_eval.html_report import render_html_report, write_html_report
from text2sql_eval.matching import (
    DatasetComparison,
    MatchingConfig,
    RowComparison,
    RowMatch,
    compare_datasets,
    compare_rows,
)
from text2sql_eval.models import (
    CaseScores,
    EvaluationCase,
    EvaluationReport,
    JudgeDecision,
    JudgeMetadata,
    MetricName,
    MetricResult,
    MetricStatus,
    MetricSummary,
    QueryResult,
)
from text2sql_eval.reporting import summarize

__all__ = [
    "CaseScores",
    "DatasetComparison",
    "EvaluationCase",
    "EvaluationReport",
    "Evaluator",
    "JudgeDecision",
    "JudgeMetadata",
    "MetricName",
    "MetricResult",
    "MetricStatus",
    "MetricSummary",
    "MatchingConfig",
    "QueryResult",
    "RowComparison",
    "RowMatch",
    "__version__",
    "compare_datasets",
    "compare_rows",
    "render_html_report",
    "score_row_count",
    "summarize",
    "write_html_report",
]
