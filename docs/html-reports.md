# HTML reports

## Open a finished report

Download [the ready-to-open synthetic demo](../examples/report-demo.html) and open the downloaded HTML file in a browser. The evaluation command produces the same complete document for your own results.

The files in `src/text2sql_eval/assets/` are internal rendering resources. In particular, `report.html.template` contains placeholders; open a generated HTML report rather than the template. Finished reports embed their CSS, JavaScript, and data in one file.

The HTML report is an offline view of existing evaluation evidence. It helps you find cases to inspect; it does not rescore SQL, run queries, or call a model.

For a guided setup and a Bash helper for demo, evaluation, and saved-report export, see [Running evaluations](running-evaluations.md).

## Create a report during evaluation

```bash
uv run text2sql-eval \
  --input examples/cases.jsonl \
  --output reports/evaluation.json
```

This writes `reports/evaluation.json` and its sibling `reports/evaluation.html`. Select a different HTML path with `--html-output`:

```bash
uv run text2sql-eval \
  --input examples/cases.jsonl \
  --output reports/evaluation.json \
  --html-output reports/review.html
```

Input, JSON output, and HTML output paths must be distinct. The command checks the paths before making model requests. It writes JSON first. If HTML rendering or writing fails, the JSON remains available and the command returns exit code `2`.

A completed evaluation with both reports returns `0` when there are no metric `ERROR` outcomes, or `1` when at least one metric has an operational error. `FAIL` and `REVIEW` are valid judgments and do not themselves make the command fail.

## Export saved results without a model

```bash
uv run text2sql-eval-report \
  --cases examples/cases.jsonl \
  --results reports/evaluation.json \
  --output reports/evaluation.html
```

This command requires neither an API key nor a model name. It performs no SQL execution or LLM invocation. It returns `0` after a successful export, including when saved metric statuses include `ERROR`. Invalid input or a writing failure returns `2`.

Two files are required because the scoring JSON contains scores and metadata, while the original cases contain questions, SQL, and execution previews. The exporter:

1. Validates the input cases and saved scoring records.
2. Requires unique case IDs in each file and identical ID sets across the files.
3. Joins by `case_id`, preserving the order of the saved scoring results.
4. Verifies that saved summary counts and rates agree with the actual statuses.
5. Renders the single-file HTML report.

Keep the original case file with each evaluation. Matching an ID cannot prove that its SQL and rows are the same evidence used for the saved judgment. The caller remains responsible for that association.

## Read the report

### Summary cards

The three cards show each metric separately, including confirmed passes, failures, reviews, errors, and decision coverage. Their denominator is the complete saved run, including `REVIEW` and `ERROR` cases.

Search and filters do not change those rates. They change only the visible cases. This keeps a filtered list from appearing to improve the underlying evaluation result.

### Find cases

Search the case list, filter by metric/status, or select confirmed judge disagreements. The disagreement filter includes a sampled `PASS` with semantic `FAIL`, or the reverse. It does not turn `REVIEW` or `ERROR` into a confirmed contradiction between the judges.

Sort the table to inspect useful groups. The table shows 25 cases per page, and the page controls apply to the current search/filter selection. Expand a case to read its evidence. The controls support keyboard navigation and a narrow-screen layout.

### Inspect a case

The expanded case shows:

- The question and available dialect/context.
- Target and generated SQL side by side.
- Separate result previews with their own column labels, counts, and truncation state.
- Each metric's normalized status, reason, evidence, and available judge metadata.

The result tables remain independent. A row at the same display position in each table is not automatically a matched record. Extra columns and different order can be permitted by the question, while differences in ranking or SQL-level `LIMIT` can change which records belong in the answer.

Each query embeds at most 50 rows. If the source supplies 80 rows, rows 51–80 are not included in the HTML as hidden data. The full `total_rows` remains visible as a count. A 50-row preview of a 1,200-row result cannot establish complete-result equality.

### Interpret uncertainty

Read normalized metric status before a judge's provisional binary verdict:

| Status | Meaning in the report |
| --- | --- |
| `PASS` | Confirmed pass under that metric's rubric. |
| `FAIL` | Confirmed failure under that metric's rubric. |
| `REVIEW` | Available evidence did not support a confirmed automatic decision. |
| `ERROR` | Execution or judge operation failed; no correctness verdict was made. |

The HTML does not resolve those outcomes or add human labels. It also does not estimate false-positive or false-negative rates without an independent human reference. In this project, positive means flagging SQL as wrong, so a false positive rejects correct SQL.

### Theme and print

Use the theme control for light or dark presentation. **Print current view** prints the overview, current page of cases, and any open case details. It does not print hidden pages or closed details. The HTML remains the interactive record.

## Use the Python functions

```python
from text2sql_eval import render_html_report, write_html_report

html = render_html_report(cases, results, title="Quarterly SQL evaluation")
path = write_html_report(cases, results, "reports/evaluation.html")
```

Both functions accept the original `EvaluationCase` records and `CaseScores` records. They validate matching IDs and render existing scores. `render_html_report()` returns an HTML string. `write_html_report()` writes it and returns a `Path`.

See [the API reference](api.md#html-reports) for signatures.

## Try the synthetic demo

```bash
uv run python examples/html_report.py --output reports/demo.html
```

The example creates 36 synthetic cases in memory and writes a report titled **Synthetic demo · Text-to-SQL evaluation**. It needs no credentials, database, or model. The examples cover all four statuses, extra information columns, conflicting judge decisions, wrong values and row counts, empty results, truncated previews, and an execution error.

All judgments and metadata in this demo are fabricated for presentation. They are not model outputs or measured evaluation performance.

## Sharing and data

The report contains the supplied SQL, context, and up to 50 result rows per query. Share it with the same care as those inputs. The file uses inline assets, with no CDN or external JavaScript framework, and can be opened offline.

Questions, SQL, cells, and judge text are treated as display data. The report is read-only: its controls change the view, not the saved scores or source records.
