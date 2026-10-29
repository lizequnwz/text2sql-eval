"""Validated input, judge output, and scoring contracts."""

from __future__ import annotations

import json
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

MetricName = Literal["row_count_match", "sampled_result_consistency", "sql_semantic"]
MetricStatus = Literal["PASS", "FAIL", "REVIEW", "ERROR"]
NonEmptyString = Annotated[str, Field(min_length=1)]


class StrictModel(BaseModel):
    """Reject unknown fields and implicit type conversions in evaluation records."""

    model_config = ConfigDict(extra="forbid", strict=True, revalidate_instances="always")


class QueryResult(StrictModel):
    """An already executed query, with a preview and the complete output row count.

    ``total_rows`` must never be the preview length unless it is also the full count.
    Rows are positional so duplicate column labels do not overwrite data.
    """

    columns: list[str]
    rows: list[list[JsonValue]]
    total_rows: int | None
    execution_error: NonEmptyString | None = None

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        if self.execution_error is not None:
            if self.total_rows is not None or self.rows:
                raise ValueError("A failed execution must have total_rows=null and no rows.")
            return self
        if self.total_rows is None or self.total_rows < 0:
            raise ValueError("A successful query requires a nonnegative complete total_rows.")
        if not self.columns:
            raise ValueError("A successful query requires column labels, even for zero rows.")
        if len(self.rows) > self.total_rows:
            raise ValueError("The supplied row count cannot exceed total_rows.")
        if any(len(row) != len(self.columns) for row in self.rows):
            raise ValueError("Each row must have one cell per column.")
        # NaN and infinity are not JSON values and cannot be compared consistently by a judge.
        json.dumps(self.rows, allow_nan=False)
        return self


class EvaluationCase(StrictModel):
    """One eligible question and its trusted reference, using the same execution conditions."""

    case_id: NonEmptyString
    question: NonEmptyString
    target_sql: NonEmptyString
    generated_sql: str
    target_result: QueryResult
    generated_result: QueryResult
    dialect: NonEmptyString | None = None
    context: NonEmptyString | None = None

    @model_validator(mode="after")
    def validate_case(self) -> Self:
        if self.target_result.execution_error is not None:
            raise ValueError("The reference must execute successfully; fix invalid gold first.")
        if not self.generated_sql.strip() and self.generated_result.execution_error is None:
            raise ValueError("Empty generated SQL requires an explicit execution/generation error.")
        if not self.question.strip() or not self.target_sql.strip() or not self.case_id.strip():
            raise ValueError("case_id, question and target_sql cannot contain only whitespace.")
        return self


class JudgeDecision(StrictModel):
    """The strict structured response requested from each LLM judge.

    All fields are required; constraints unsupported by provider JSON schemas are avoided.
    A review flag overrides the provisional binary verdict when scoring.
    """

    verdict: Literal["PASS", "FAIL"] = Field(
        description="Binary judgment. Provisional only when needs_review is true."
    )
    reason: str = Field(description="Brief, evidence-based explanation, not private reasoning.")
    needs_review: bool = Field(
        description="True if available evidence does not support a confirmed automatic verdict."
    )
    evidence: list[str] = Field(
        description="Relevant SQL clauses, observed cells, or specific missing evidence."
    )

    @field_validator("reason")
    @classmethod
    def meaningful_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("The judge must provide a nonempty reason.")
        return value.strip()


class JudgeMetadata(StrictModel):
    model: str
    prompt_sha256: str
    elapsed_seconds: float
    token_usage: dict[str, int] | None = None


class MetricResult(StrictModel):
    name: MetricName
    status: MetricStatus
    reason: str
    judgment: JudgeDecision | None = None
    metadata: JudgeMetadata | None = None
    error_type: str | None = None
    score: Literal[0, 1] | None = None

    @model_validator(mode="after")
    def canonical_score(self) -> Self:
        """Derive the score, also validating it when reloading a saved report."""
        expected = 1 if self.status == "PASS" else 0 if self.status == "FAIL" else None
        if "score" in self.model_fields_set and self.score != expected:
            raise ValueError("score must agree with status; REVIEW and ERROR have no score.")
        self.score = expected
        if self.judgment is not None:
            status = "REVIEW" if self.judgment.needs_review else self.judgment.verdict
            if self.status != status:
                raise ValueError("The metric status must respect the judge's review flag/verdict.")
        return self


class CaseScores(StrictModel):
    case_id: str
    row_count_match: MetricResult
    sampled_result_consistency: MetricResult
    sql_semantic: MetricResult

    @model_validator(mode="after")
    def metric_names_match_fields(self) -> Self:
        for name in ("row_count_match", "sampled_result_consistency", "sql_semantic"):
            if getattr(self, name).name != name:
                raise ValueError(f"{name} must contain a metric with that same name.")
        return self


class MetricSummary(StrictModel):
    cases: int
    passed: int
    failed: int
    review: int
    errors: int
    pass_rate: float | None
    decision_coverage: float | None


class EvaluationReport(StrictModel):
    """The existing saved JSON shape, now validated for offline report export."""

    package_version: NonEmptyString
    results: list[CaseScores]
    summary: dict[MetricName, MetricSummary]
