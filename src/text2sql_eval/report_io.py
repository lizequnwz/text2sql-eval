"""Shared input validation and atomic report writes; no provider clients."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from pydantic import ValidationError

from text2sql_eval.models import EvaluationCase, EvaluationReport
from text2sql_eval.reporting import summarize


def load_cases(path: Path, *, allow_empty: bool = False) -> list[EvaluationCase]:
    """Validate all JSONL records before evaluation or saved-report rendering."""
    cases: list[EvaluationCase] = []
    ids: set[str] = set()
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                case = EvaluationCase.model_validate_json(line)
            except ValidationError as exc:
                raise ValueError(f"Invalid case at {path}:{line_number}: {exc}") from exc
            if case.case_id in ids:
                raise ValueError(f"Duplicate case_id at {path}:{line_number}: {case.case_id}")
            ids.add(case.case_id)
            cases.append(case)
    if not cases and not allow_empty:
        raise ValueError("The input contains no evaluation cases.")
    return cases


def load_report(path: Path) -> EvaluationReport:
    """Reject inconsistent summaries rather than displaying unverified totals."""
    report = EvaluationReport.model_validate_json(path.read_text(encoding="utf-8"))
    if report.summary != summarize(report.results):
        raise ValueError("Saved summary does not match the validated case results.")
    return report


def require_distinct_paths(*paths: Path) -> None:
    """Protect inputs and separate outputs, including symlinks and existing hard links."""
    for index, first in enumerate(paths):
        for second in paths[index + 1 :]:
            same_path = first.resolve() == second.resolve()
            same_file = first.exists() and second.exists() and first.samefile(second)
            if same_path or same_file:
                raise ValueError(f"Input and output paths must be distinct: {first} and {second}.")


def write_text_atomic(path: Path, content: str) -> Path:
    """Replace one UTF-8 report only after its complete contents have been written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(content)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return path


def write_json_report(path: Path, report: EvaluationReport) -> Path:
    return write_text_atomic(path, report.model_dump_json(indent=2) + "\n")
