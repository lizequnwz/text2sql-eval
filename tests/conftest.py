"""Offline fixtures: no API key, provider connection, or SQL execution is needed."""

from __future__ import annotations

import inspect
import json
from collections.abc import Callable
from typing import Any

import pytest
from langchain_core.messages import AIMessage

from text2sql_eval import EvaluationCase, JudgeDecision, QueryResult


def decision(
    verdict: str = "PASS",
    *,
    needs_review: bool = False,
    reason: str = "Supported by the supplied evidence.",
) -> dict[str, Any]:
    return {
        "parsed": JudgeDecision(
            verdict=verdict,
            reason=reason,
            needs_review=needs_review,
            evidence=["SELECT customer_id, SUM(amount) AS total_sales"],
        ),
        "raw": AIMessage(
            content="",
            usage_metadata={"input_tokens": 20, "output_tokens": 10, "total_tokens": 30},
        ),
        "parsing_error": None,
    }


def payload(messages: list[Any]) -> dict[str, Any]:
    return json.loads(messages[-1].content)


class RecordingModel:
    """A duck-typed ChatOpenAI replacement that only returns scripted decisions."""

    model_name = "offline-test-model"

    def __init__(self, responder: Callable[[list[Any]], Any] | None = None) -> None:
        self.responder = responder or (lambda messages: decision())
        self.calls: list[list[Any]] = []
        self.bindings: list[tuple[Any, dict[str, Any]]] = []

    def with_structured_output(self, schema: Any, **kwargs: Any) -> RecordingRunnable:
        self.bindings.append((schema, kwargs))
        return RecordingRunnable(self)


class RecordingRunnable:
    def __init__(self, owner: RecordingModel) -> None:
        self.owner = owner

    def invoke(self, messages: list[Any], **kwargs: Any) -> Any:
        self.owner.calls.append(messages)
        response = self.owner.responder(messages)
        if isinstance(response, Exception):
            raise response
        return response

    async def ainvoke(self, messages: list[Any], **kwargs: Any) -> Any:
        self.owner.calls.append(messages)
        response = self.owner.responder(messages)
        if inspect.isawaitable(response):
            response = await response
        if isinstance(response, Exception):
            raise response
        return response


@pytest.fixture
def make_case() -> Callable[..., EvaluationCase]:
    def factory(**overrides: Any) -> EvaluationCase:
        fields: dict[str, Any] = {
            "case_id": "customer-sales",
            "question": "Return total sales for each customer.",
            "target_sql": (
                "SELECT customer_id, SUM(amount) AS total_sales FROM orders GROUP BY customer_id"
            ),
            "generated_sql": (
                "SELECT customer_id, SUM(amount) AS total_sales FROM orders GROUP BY customer_id"
            ),
            "target_result": QueryResult(
                columns=["customer_id", "total_sales"],
                rows=[[1, 100], [2, 200]],
                total_rows=2,
            ),
            "generated_result": QueryResult(
                columns=["customer_id", "total_sales"],
                rows=[[1, 100], [2, 200]],
                total_rows=2,
            ),
        }
        fields.update(overrides)
        return EvaluationCase(**fields)

    return factory
