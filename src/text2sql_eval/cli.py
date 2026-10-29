"""JSONL in, auditable JSON report out."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from langchain_openai import ChatOpenAI

from text2sql_eval import __version__
from text2sql_eval.evaluator import Evaluator
from text2sql_eval.html_report import write_html_report
from text2sql_eval.models import EvaluationReport
from text2sql_eval.report_io import load_cases, require_distinct_paths, write_json_report
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


def main(argv: list[str] | None = None) -> int:
    """Run all three metrics, preserving judge errors in the output report."""
    parser = argparse.ArgumentParser(
        description="Score pre-executed text-to-SQL results with two structured LLM judges."
    )
    parser.add_argument("--input", type=Path, required=True, help="Evaluation cases as JSONL.")
    parser.add_argument("--output", type=Path, required=True, help="Destination JSON report.")
    parser.add_argument(
        "--html-output", type=Path, help="HTML destination (default: JSON path with .html suffix)."
    )
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
    html_output = (
        args.html_output if args.html_output is not None else args.output.with_suffix(".html")
    )
    try:
        require_distinct_paths(args.input, args.output, html_output)
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
        report = EvaluationReport(package_version=__version__, results=results, summary=summary)
        write_json_report(args.output, report)
    except OSError as exc:
        print(f"Could not write the report: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Evaluation interrupted; no completed report was written.", file=sys.stderr)
        return 130

    try:
        write_html_report(cases, results, html_output, package_version=__version__)
    except (OSError, ValueError) as exc:
        print(
            f"JSON report saved to {args.output}, but could not write the HTML report: {exc}. "
            "Use text2sql-eval-report to retry rendering without rerunning the judges.",
            file=sys.stderr,
        )
        return 2

    print(json.dumps({name: item.model_dump() for name, item in summary.items()}, indent=2))
    print(f"JSON report: {args.output.resolve()}", file=sys.stderr)
    print(f"HTML report: {html_output.resolve()}", file=sys.stderr)
    return int(
        any(getattr(result, name).status == "ERROR" for result in results for name in METRIC_NAMES)
    )
