"""A deterministic metric and two independent structured ChatOpenAI calls."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Sequence
from time import perf_counter
from typing import Any

from langchain_core.messages import BaseMessage
from langchain_openai import ChatOpenAI

from text2sql_eval.models import (
    CaseScores,
    EvaluationCase,
    JudgeDecision,
    JudgeMetadata,
    MetricName,
    MetricResult,
)
from text2sql_eval.prompts import (
    build_sampled_messages,
    build_semantic_messages,
    system_prompt,
)


def _execution_error(name: MetricName, reason: str) -> MetricResult:
    return MetricResult(name=name, status="ERROR", reason=reason, error_type="InputExecutionError")


def score_row_count(case: EvaluationCase) -> MetricResult:
    """Compare full counts, independent of supplied preview lengths and column counts."""
    case = EvaluationCase.model_validate(case)
    if case.generated_result.execution_error is not None:
        return _execution_error("row_count_match", "Generated query did not execute successfully.")
    target = case.target_result.total_rows
    generated = case.generated_result.total_rows
    return MetricResult(
        name="row_count_match",
        status="PASS" if target == generated else "FAIL",
        reason=f"Complete row counts: target={target}, generated={generated}.",
    )


def _validated_cases(cases: Sequence[EvaluationCase]) -> list[EvaluationCase]:
    validated = [EvaluationCase.model_validate(case) for case in cases]
    ids = [case.case_id for case in validated]
    if len(ids) != len(set(ids)):
        raise ValueError("case_id must be unique within an evaluation batch.")
    return validated


class Evaluator:
    """Score pre-executed SQL results using a caller-configured ChatOpenAI model.

    Each successful case normally uses two independent LLM requests. There are no
    database connections, tools, conversation memory, or cross-judge messages.
    Provider retries and timeouts belong to the supplied ChatOpenAI instance.
    """

    def __init__(self, llm: ChatOpenAI) -> None:
        self._model_name = llm.model_name
        self._judge = llm.with_structured_output(
            JudgeDecision, method="json_schema", strict=True, include_raw=True
        )
        self._system_prompts = {
            metric: system_prompt(metric)
            for metric in ("sampled_result_consistency", "sql_semantic")
        }
        self._prompt_hashes = {
            metric: hashlib.sha256(content.encode("utf-8")).hexdigest()
            for metric, content in self._system_prompts.items()
        }

    def _finish(self, metric: MetricName, response: dict[str, Any], started: float) -> MetricResult:
        raw = response.get("raw")
        raw_usage = getattr(raw, "usage_metadata", None)
        usage = None
        if isinstance(raw_usage, dict):
            usage = {
                key: raw_usage[key]
                for key in ("input_tokens", "output_tokens", "total_tokens")
                if isinstance(raw_usage.get(key), int)
            }
        metadata = JudgeMetadata(
            model=self._model_name,
            prompt_sha256=self._prompt_hashes[metric],
            elapsed_seconds=perf_counter() - started,
            token_usage=usage,
        )
        parsing_error = response.get("parsing_error")
        if parsing_error is not None or response.get("parsed") is None:
            return MetricResult(
                name=metric,
                status="ERROR",
                reason="Judge did not return a valid structured decision; no SQL verdict was made.",
                metadata=metadata,
                error_type=type(parsing_error).__name__ if parsing_error else "EmptyJudgeResponse",
            )
        decision = JudgeDecision.model_validate(response["parsed"])
        return MetricResult(
            name=metric,
            status="REVIEW" if decision.needs_review else decision.verdict,
            reason=decision.reason,
            judgment=decision,
            metadata=metadata,
        )

    def _call_error(self, metric: MetricName, exc: Exception, started: float) -> MetricResult:
        # Avoid copying provider request bodies, API keys, or dataset contents into error reports.
        return MetricResult(
            name=metric,
            status="ERROR",
            reason=f"Judge call failed ({type(exc).__name__}); no SQL verdict was made.",
            error_type=type(exc).__name__,
            metadata=JudgeMetadata(
                model=self._model_name,
                prompt_sha256=self._prompt_hashes[metric],
                elapsed_seconds=perf_counter() - started,
            ),
        )

    def _invoke(self, metric: MetricName, messages: list[BaseMessage]) -> MetricResult:
        messages[0] = messages[0].model_copy(update={"content": self._system_prompts[metric]})
        started = perf_counter()
        try:
            return self._finish(metric, self._judge.invoke(messages), started)
        except Exception as exc:
            return self._call_error(metric, exc, started)

    async def _ainvoke(self, metric: MetricName, messages: list[BaseMessage]) -> MetricResult:
        messages[0] = messages[0].model_copy(update={"content": self._system_prompts[metric]})
        started = perf_counter()
        try:
            return self._finish(metric, await self._judge.ainvoke(messages), started)
        except Exception as exc:
            return self._call_error(metric, exc, started)

    @staticmethod
    def _sampled_error(case: EvaluationCase) -> MetricResult | None:
        if case.generated_result.execution_error is not None:
            return _execution_error(
                "sampled_result_consistency", "Generated query has no successful result to compare."
            )
        return None

    @staticmethod
    def _semantic_error(case: EvaluationCase) -> MetricResult | None:
        if not case.generated_sql.strip():
            return _execution_error("sql_semantic", "There is no generated SQL to assess.")
        return None

    def evaluate(self, case: EvaluationCase) -> CaseScores:
        """Score one case; a judge error does not prevent the other judge from running."""
        case = EvaluationCase.model_validate(case)
        sampled = self._sampled_error(case)
        if sampled is None:
            sampled = self._invoke("sampled_result_consistency", build_sampled_messages(case))
        semantic = self._semantic_error(case)
        if semantic is None:
            semantic = self._invoke("sql_semantic", build_semantic_messages(case))
        return CaseScores(
            case_id=case.case_id,
            row_count_match=score_row_count(case),
            sampled_result_consistency=sampled,
            sql_semantic=semantic,
        )

    async def aevaluate(self, case: EvaluationCase) -> CaseScores:
        """Run the two independent requests concurrently for one case."""
        case = EvaluationCase.model_validate(case)

        async def sampled_score() -> MetricResult:
            existing = self._sampled_error(case)
            if existing is not None:
                return existing
            return await self._ainvoke("sampled_result_consistency", build_sampled_messages(case))

        async def semantic_score() -> MetricResult:
            existing = self._semantic_error(case)
            if existing is not None:
                return existing
            return await self._ainvoke("sql_semantic", build_semantic_messages(case))

        sampled, semantic = await asyncio.gather(sampled_score(), semantic_score())
        return CaseScores(
            case_id=case.case_id,
            row_count_match=score_row_count(case),
            sampled_result_consistency=sampled,
            sql_semantic=semantic,
        )

    def evaluate_many(self, cases: Sequence[EvaluationCase]) -> list[CaseScores]:
        """Evaluate a batch in input order after validating unique identifiers."""
        return [self.evaluate(case) for case in _validated_cases(cases)]

    async def aevaluate_many(
        self, cases: Sequence[EvaluationCase], *, concurrency: int = 4
    ) -> list[CaseScores]:
        """Bound active cases, each of which can make two concurrent LLM requests."""
        if isinstance(concurrency, bool) or not isinstance(concurrency, int) or concurrency < 1:
            raise ValueError("concurrency must be a positive integer.")
        cases = _validated_cases(cases)
        semaphore = asyncio.Semaphore(concurrency)

        async def evaluate_one(case: EvaluationCase) -> CaseScores:
            async with semaphore:
                return await self.aevaluate(case)

        return list(await asyncio.gather(*(evaluate_one(case) for case in cases)))
