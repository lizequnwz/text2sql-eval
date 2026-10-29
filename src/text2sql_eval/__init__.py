"""Three explicit scores for pre-executed text-to-SQL predictions."""

from text2sql_eval.evaluator import Evaluator, score_row_count
from text2sql_eval.models import (
    CaseScores,
    EvaluationCase,
    JudgeDecision,
    JudgeMetadata,
    MetricName,
    MetricResult,
    MetricStatus,
    MetricSummary,
    QueryResult,
)
from text2sql_eval.reporting import summarize

__version__ = "0.1.0"

__all__ = [
    "CaseScores",
    "EvaluationCase",
    "Evaluator",
    "JudgeDecision",
    "JudgeMetadata",
    "MetricName",
    "MetricResult",
    "MetricStatus",
    "MetricSummary",
    "QueryResult",
    "score_row_count",
    "summarize",
]
