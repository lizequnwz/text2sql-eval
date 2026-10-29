"""Render saved results with their original cases, without model credentials."""

from __future__ import annotations

import argparse
from pathlib import Path

from text2sql_eval.html_report import write_html_report
from text2sql_eval.report_io import load_cases, load_report, require_distinct_paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Create a standalone HTML reader from saved scores and original cases."
    )
    parser.add_argument(
        "--cases", type=Path, required=True, help="Original evaluation cases JSONL."
    )
    parser.add_argument("--results", type=Path, required=True, help="Saved evaluation JSON report.")
    parser.add_argument("--output", type=Path, required=True, help="Destination standalone HTML.")
    args = parser.parse_args(argv)
    try:
        require_distinct_paths(args.cases, args.results, args.output)
        cases = load_cases(args.cases, allow_empty=True)
        report = load_report(args.results)
        write_html_report(
            cases, report.results, args.output, package_version=report.package_version
        )
    except (OSError, ValueError) as exc:
        parser.error(f"Could not create the HTML report: {exc}")
    print(f"HTML report written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
