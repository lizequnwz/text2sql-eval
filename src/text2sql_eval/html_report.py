"""An offline, self-contained reader for evaluation scores and source evidence."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path

from pydantic import JsonValue

from text2sql_eval._version import __version__
from text2sql_eval.models import CaseScores, EvaluationCase, QueryResult
from text2sql_eval.preview import PREVIEW_LIMIT, preview_result
from text2sql_eval.report_io import write_text_atomic
from text2sql_eval.reporting import METRIC_NAMES, summarize


def _display_cell(value: JsonValue) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list, bool)):
        return json.dumps(value, ensure_ascii=False, allow_nan=False)
    return str(value)


def _html_preview(result: QueryResult) -> dict[str, object]:
    preview = preview_result(result)
    # Format in Python so JavaScript does not round large SQL integers during display.
    preview["display_rows"] = [
        [_display_cell(cell) for cell in row] for row in result.rows[:PREVIEW_LIMIT]
    ]
    return preview


def _safe_json(payload: dict[str, object]) -> str:
    """Prevent HTML/script termination even inside an inert application/json element."""
    content = json.dumps(payload, ensure_ascii=True, allow_nan=False, separators=(",", ":"))
    return content.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")


def render_html_report(
    cases: Sequence[EvaluationCase],
    results: Sequence[CaseScores],
    *,
    package_version: str = __version__,
    title: str = "Text-to-SQL evaluation report",
) -> str:
    """Join evidence by ID and return a shareable HTML document, without LLM calls.

    The document includes SQL, supplied context and up to fifty rows per result.
    Both ID sets must match exactly. Saved result order is the reading order.
    """
    if not package_version.strip() or not title.strip():
        raise ValueError("package_version and title must contain text.")
    validated_cases = [EvaluationCase.model_validate(case) for case in cases]
    validated_results = [CaseScores.model_validate(result) for result in results]
    by_id = {case.case_id: case for case in validated_cases}
    if len(by_id) != len(validated_cases):
        raise ValueError("Duplicate case_id in original cases.")
    summary = summarize(validated_results)
    result_ids = {result.case_id for result in validated_results}
    if result_ids != set(by_id):
        missing = sorted(result_ids - set(by_id))
        extra = sorted(set(by_id) - result_ids)
        raise ValueError(
            f"Case IDs must match exactly; missing original cases={missing}, "
            f"original cases without scores={extra}."
        )
    joined = []
    for result in validated_results:
        case = by_id[result.case_id]
        item = case.model_dump(mode="json", exclude={"target_result", "generated_result"})
        item["target_result"] = _html_preview(case.target_result)
        item["generated_result"] = _html_preview(case.generated_result)
        item["scores"] = {
            name: getattr(result, name).model_dump(mode="json") for name in METRIC_NAMES
        }
        joined.append(item)
    payload = {
        "title": title,
        "package_version": package_version,
        "rendered_at": datetime.now(UTC).isoformat(),
        "summary": {name: item.model_dump(mode="json") for name, item in summary.items()},
        "cases": joined,
    }
    assets = files("text2sql_eval").joinpath("assets")
    template = assets.joinpath("report.html").read_text(encoding="utf-8")
    # One replacement pass prevents data containing placeholder names from becoming markup.
    pieces = {
        "__REPORT_CSS__": assets.joinpath("report.css").read_text(encoding="utf-8"),
        "__REPORT_JS__": assets.joinpath("report.js").read_text(encoding="utf-8"),
        "__REPORT_DATA__": _safe_json(payload),
    }
    for marker in pieces:
        if template.count(marker) != 1:
            raise ValueError(f"The HTML template must contain {marker} exactly once.")
    return re.sub("|".join(pieces), lambda match: pieces[match.group()], template)


def write_html_report(
    cases: Sequence[EvaluationCase],
    results: Sequence[CaseScores],
    path: str | Path,
    *,
    package_version: str = __version__,
    title: str = "Text-to-SQL evaluation report",
) -> Path:
    """Render then atomically write a report, preserving an existing file on error."""
    html = render_html_report(cases, results, package_version=package_version, title=title)
    return write_text_atomic(Path(path), html)
