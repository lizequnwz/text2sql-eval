"""Load versioned prompt resources and build isolated judge inputs."""

from __future__ import annotations

import hashlib
import json
from importlib.resources import files

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from text2sql_eval.models import EvaluationCase
from text2sql_eval.preview import preview_result

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


def _messages(metric: str, payload: dict[str, object]) -> list[BaseMessage]:
    return [
        SystemMessage(content=system_prompt(metric)),
        HumanMessage(content=json.dumps(payload, ensure_ascii=False, allow_nan=False)),
    ]


def build_sampled_messages(case: EvaluationCase) -> list[BaseMessage]:
    """Give the sampled judge SQL plus at most 50 rows from each supplied preview."""
    payload = _question_payload(case)
    payload["target_result"] = preview_result(case.target_result)
    payload["generated_result"] = preview_result(case.generated_result)
    return _messages("sampled_result_consistency", payload)


def build_semantic_messages(case: EvaluationCase) -> list[BaseMessage]:
    """Give the semantic judge the question/SQL context, never execution previews."""
    return _messages("sql_semantic", _question_payload(case))
