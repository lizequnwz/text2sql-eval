"""Load versioned prompt resources and build isolated judge inputs."""

from __future__ import annotations

import hashlib
import json
from importlib.resources import files

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from text2sql_eval.models import EvaluationCase, QueryResult

PREVIEW_LIMIT = 50
PROMPT_FILES = {
    "sampled_result_consistency": "sampled_result_consistency.md",
    "sql_semantic": "sql_semantics.md",
}


def system_prompt(metric: str) -> str:
    """Read the exact packaged rubric, also available for human inspection."""
    root = files("text2sql_eval").joinpath("prompts")
    common = root.joinpath("common.md").read_text(encoding="utf-8")
    specific = root.joinpath(PROMPT_FILES[metric]).read_text(encoding="utf-8")
    return f"{common.rstrip()}\n\n{specific.strip()}\n"


def prompt_sha256(metric: str) -> str:
    """A report fingerprint for the common and metric-specific system instructions."""
    return hashlib.sha256(system_prompt(metric).encode("utf-8")).hexdigest()


def _question_payload(case: EvaluationCase) -> dict[str, object]:
    # Explicit fields keep result rows/counts out of the semantic judge's context.
    return {
        "question": case.question,
        "target_sql": case.target_sql,
        "generated_sql": case.generated_sql,
        "dialect": case.dialect,
        "context": case.context,
    }


def _preview(result: QueryResult) -> dict[str, object]:
    shown_rows = min(len(result.rows), PREVIEW_LIMIT)
    return {
        "columns": result.columns,
        "rows": result.rows[:PREVIEW_LIMIT],
        "total_rows": result.total_rows,
        "provided_rows": len(result.rows),
        "shown_rows": shown_rows,
        "truncated": result.total_rows is not None and result.total_rows > shown_rows,
        "execution_error": result.execution_error,
    }


def _messages(metric: str, payload: dict[str, object]) -> list[BaseMessage]:
    return [
        SystemMessage(content=system_prompt(metric)),
        HumanMessage(content=json.dumps(payload, ensure_ascii=False, allow_nan=False)),
    ]


def build_sampled_messages(case: EvaluationCase) -> list[BaseMessage]:
    """Give the sampled judge SQL plus at most 50 rows from each supplied preview."""
    payload = _question_payload(case)
    payload["target_result"] = _preview(case.target_result)
    payload["generated_result"] = _preview(case.generated_result)
    return _messages("sampled_result_consistency", payload)


def build_semantic_messages(case: EvaluationCase) -> list[BaseMessage]:
    """Give the semantic judge the question/SQL context, never execution previews."""
    return _messages("sql_semantic", _question_payload(case))
