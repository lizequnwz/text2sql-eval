"""JSONL in, auditable JSON report out."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

from langchain_openai import ChatOpenAI
from pydantic import ValidationError

from text2sql_eval import __version__
from text2sql_eval.evaluator import Evaluator
from text2sql_eval.models import EvaluationCase
from text2sql_eval.reporting import METRIC_NAMES, summarize


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _nonnegative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be a nonnegative integer")
    return parsed


def load_cases(path: Path) -> list[EvaluationCase]:
    """Validate every record before making any paid requests; never drop invalid cases."""
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
    if not cases:
        raise ValueError("The input contains no evaluation cases.")
    return cases


def _write_report(path: Path, content: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump(content, handle, ensure_ascii=False, allow_nan=False, indent=2)
            handle.write("\n")
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    """Run all three metrics, preserving judge errors in the output report."""
    parser = argparse.ArgumentParser(
        description="Score pre-executed text-to-SQL results with two structured LLM judges."
    )
    parser.add_argument("--input", type=Path, required=True, help="Evaluation cases as JSONL.")
    parser.add_argument("--output", type=Path, required=True, help="Destination JSON report.")
    parser.add_argument("--model", default=os.environ.get("OPENAI_MODEL"))
    parser.add_argument("--base-url", default=os.environ.get("OPENAI_BASE_URL"))
    parser.add_argument(
        "--concurrency", type=_positive_int, default=4, help="Active cases (default 4)."
    )
    parser.add_argument("--timeout", type=float, default=60.0, help="Provider timeout in seconds.")
    parser.add_argument("--max-retries", type=_nonnegative_int, default=2)
    parser.add_argument("--temperature", type=float, help="Only set if your model supports it.")
    args = parser.parse_args(argv)
    if not args.model or not args.model.strip():
        parser.error(
            "Set --model or OPENAI_MODEL to a model with strict structured-output support."
        )
    if not 0 < args.timeout < float("inf"):
        parser.error("--timeout must be a positive, finite number.")
    if args.temperature is not None and not 0 <= args.temperature <= 2:
        parser.error("--temperature must be between 0 and 2.")
    if args.input.resolve() == args.output.resolve():
        parser.error("--output must not overwrite the input dataset.")

    try:
        cases = load_cases(args.input)
        kwargs: dict[str, object] = {
            "model": args.model,
            "timeout": args.timeout,
            "max_retries": args.max_retries,
        }
        if args.base_url:
            kwargs["base_url"] = args.base_url
        if args.temperature is not None:
            kwargs["temperature"] = args.temperature
        evaluator = Evaluator(ChatOpenAI(**kwargs))
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    except Exception as exc:
        # Some SDK setup failures (including missing credentials) are not ValueError.
        parser.error(
            f"Could not configure the judge ({type(exc).__name__}). "
            "Check OPENAI_API_KEY, the model, endpoint and structured-output support."
        )

    try:
        results = asyncio.run(evaluator.aevaluate_many(cases, concurrency=args.concurrency))
        summary = summarize(results)
        report = {
            "package_version": __version__,
            "results": [result.model_dump(mode="json") for result in results],
            "summary": {name: item.model_dump(mode="json") for name, item in summary.items()},
        }
        _write_report(args.output, report)
    except OSError as exc:
        print(f"Could not write the report: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Evaluation interrupted; no completed report was written.", file=sys.stderr)
        return 130

    print(json.dumps(report["summary"], indent=2))
    return int(
        any(getattr(result, name).status == "ERROR" for result in results for name in METRIC_NAMES)
    )
