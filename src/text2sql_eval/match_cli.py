"""Compare complete datasets without SQL execution, credentials, or model calls."""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path

from text2sql_eval.matching import MatchingConfig, compare_datasets
from text2sql_eval.report_io import require_distinct_paths, write_text_atomic

POLICIES = ("equal", "target_subset", "generated_subset", "bidirectional")


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _reject_constant(value: str) -> None:
    raise ValueError(f"{value} is not valid JSON; use null for missing values.")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    record: dict[str, object] = {}
    for key, value in pairs:
        if key in record:
            raise ValueError(f"Duplicate JSON object key: {key!r}. Use positional rows instead.")
        record[key] = value
    return record


def _load_dataset(path: Path) -> object:
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            parse_float=Decimal,
            parse_constant=_reject_constant,
            object_pairs_hook=_unique_object,
        )
    except (OSError, ValueError) as exc:
        raise ValueError(f"Could not read dataset {path}: {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    """Write the complete comparison and return 0 accepted, 1 rejected, or 2 invalid."""
    defaults = MatchingConfig()
    parser = argparse.ArgumentParser(
        description=(
            "Compare complete datasets using duplicate-aware row-value subsets and "
            "one-to-one row matching. No SQL or LLM calls."
        )
    )
    parser.add_argument("--target", type=Path, required=True, help="Target dataset as JSON.")
    parser.add_argument("--generated", type=Path, required=True, help="Generated dataset as JSON.")
    parser.add_argument(
        "--row-policy",
        choices=POLICIES,
        default=defaults.row_policy,
        help=f"Accepted within-row relationship (default: {defaults.row_policy}).",
    )
    parser.add_argument(
        "--dataset-policy",
        choices=POLICIES,
        default=defaults.dataset_policy,
        help=f"Required across-row coverage (default: {defaults.dataset_policy}).",
    )
    parser.add_argument(
        "--max-candidate-edges",
        type=_positive_int,
        default=defaults.max_candidate_edges,
        help="Stop with an error if the unique-row matching graph exceeds this size.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Write JSON atomically here instead of standard output.",
    )
    args = parser.parse_args(argv)
    try:
        if args.output is not None:
            # Comparing a file with itself is valid; neither input may be overwritten.
            require_distinct_paths(args.target, args.output)
            require_distinct_paths(args.generated, args.output)
        config = MatchingConfig(
            row_policy=args.row_policy,
            dataset_policy=args.dataset_policy,
            max_candidate_edges=args.max_candidate_edges,
        )
        result = compare_datasets(
            _load_dataset(args.target), _load_dataset(args.generated), config=config
        )
        content = result.model_dump_json(indent=2) + "\n"
        if args.output is None:
            print(content, end="")
        else:
            write_text_atomic(args.output, content)
            print(f"Comparison written to {args.output.resolve()}", file=sys.stderr)
    except (OSError, TypeError, ValueError) as exc:
        parser.error(f"Could not compare datasets: {exc}")
    return 0 if result.accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
