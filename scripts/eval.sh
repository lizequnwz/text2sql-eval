#!/usr/bin/env bash
# Run from any directory. User-supplied relative paths keep their usual meaning.
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: bash scripts/eval.sh <command> [options]

Commands:
  setup   Install the locked Python runtime dependencies with uv.
  demo    Generate an HTML demo with fabricated data and no LLM calls.
  eval    Score prepared cases and write both JSON and HTML reports.
  report  Generate HTML from saved scores and their original cases.

Examples (from the repository root):
  bash scripts/eval.sh setup
  bash scripts/eval.sh demo
  bash scripts/eval.sh eval --input data/cases.jsonl
  bash scripts/eval.sh report --cases data/cases.jsonl --results reports/evaluation.json

Default outputs are in this repository's reports/ directory.
Paths supplied in options are relative to your current working directory.
The eval command requires OPENAI_API_KEY and --model or OPENAI_MODEL.
Environment files are not loaded automatically.

Use: bash scripts/eval.sh <command> --help
USAGE
}

fail() {
  printf 'Error: %s\n' "$1" >&2
  exit 2
}

command_name="${1:-help}"
if [[ $# -gt 0 ]]; then shift; fi
case "$command_name" in
  help|-h|--help) usage; exit 0 ;;
  setup|demo|eval|report) ;;
  *) usage >&2; fail "Unknown command: $command_name" ;;
esac

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  case "$command_name" in
    setup) printf 'Usage: bash scripts/eval.sh setup\nInstall the locked runtime dependencies. No API credentials are needed.\n' ;;
    demo) printf 'Usage: bash scripts/eval.sh demo [--output PATH]\nWrite a synthetic HTML report. No SQL execution or model calls.\n' ;;
    eval) printf 'Usage: bash scripts/eval.sh eval --input CASES.jsonl [--output RESULTS.json] [--html-output REPORT.html] [--model MODEL] [--base-url URL] [--concurrency N] [--timeout SECONDS] [--max-retries N] [--temperature VALUE]\nThe input must include generated SQL, execution previews, and full output row counts.\n' ;;
    report) printf 'Usage: bash scripts/eval.sh report --cases CASES.jsonl --results RESULTS.json [--output REPORT.html]\nRender saved judgments without model credentials or calls.\n' ;;
  esac
  exit 0
fi

command -v uv >/dev/null 2>&1 || fail 'uv is required. Install it using https://docs.astral.sh/uv/getting-started/installation/'
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"

if [[ "$command_name" == "setup" ]]; then
  [[ $# -eq 0 ]] || fail 'setup accepts no options; use the uv command directly for advanced setup.'
  if uv sync --project "$project_root" --locked --no-dev; then
    printf 'Setup complete. Next: bash "%s/scripts/eval.sh" demo\n' "$project_root"
    exit 0
  fi
  fail 'Setup failed. Check the uv output above, then run setup again.'
fi

[[ -x "$project_root/.venv/bin/python" ]] || fail "Run setup first: bash \"$project_root/scripts/eval.sh\" setup"

case "$command_name" in
  demo)
    exec uv run --project "$project_root" --locked --no-sync --no-env-file \
      python "$project_root/examples/html_report.py" \
      --output "$project_root/reports/demo.html" "$@"
    ;;
  eval)
    [[ -n "${OPENAI_API_KEY:-}" ]] || fail 'Set OPENAI_API_KEY in your shell before running eval.'
    exec uv run --project "$project_root" --locked --no-sync --no-env-file \
      text2sql-eval --output "$project_root/reports/evaluation.json" "$@"
    ;;
  report)
    exec uv run --project "$project_root" --locked --no-sync --no-env-file \
      text2sql-eval-report --output "$project_root/reports/evaluation.html" "$@"
    ;;
esac
