# Run evaluations and generate reports

Use [`scripts/eval.sh`](../scripts/eval.sh) for setup, evaluation, and HTML export. It runs the existing Python commands with the project's locked dependencies.

## 1. Set up once

You need Python 3.11 or later, [uv](https://docs.astral.sh/uv/), and Bash.

```bash
git clone https://github.com/lizequnwz/text2sql-eval.git
cd text2sql-eval
bash scripts/eval.sh setup
```

For an existing checkout, start with `cd text2sql-eval` and run the setup command. Run setup again after pulling dependency changes. The helper uses the prepared environment when running commands; it does not install packages on each evaluation.

## 2. Try HTML generation without an API key

```bash
bash scripts/eval.sh demo
```

Open `reports/demo.html` in your browser. This generates 36 synthetic cases and canned decisions. It makes no SQL or model calls and does not measure your system's accuracy.

To choose another destination:

```bash
bash scripts/eval.sh demo --output reports/my-demo.html
```

Open the generated `.html` file. Files ending in `.html.template` are internal source templates.

## 3. Prepare your evaluation input

Your original test set can contain just questions and target SQL. Before scoring, your existing application must generate SQL and execute both queries:

```text
Question + target SQL
        ↓
Your text-to-SQL system generates SQL
        ↓
Your execution pipeline runs target SQL and generated SQL
        ↓
Save SQL, column names, preview rows, and complete row counts as JSONL
        ↓
Run this package's three scoring metrics
        ↓
Read the JSON and HTML reports
```

This package starts at the scoring step. It does not generate SQL, connect to your database, or execute queries.

Create a JSONL file with **one complete case per line**. For example, save this single line as `cases.jsonl`:

```json
{"case_id":"sales-001","question":"What is the total sales amount for each customer?","target_sql":"SELECT customer_id, SUM(amount) AS total_sales FROM orders GROUP BY customer_id","generated_sql":"SELECT customer_id, SUM(amount) AS total_sales FROM orders GROUP BY customer_id ORDER BY total_sales DESC","target_result":{"columns":["customer_id","total_sales"],"rows":[[1,100],[2,200]],"total_rows":2},"generated_result":{"columns":["customer_id","total_sales"],"rows":[[2,200],[1,100]],"total_rows":2}}
```

Replace the example SQL and data with evidence from your execution pipeline. Use the same database snapshot, permissions, timezone, and date basis for both executions.

- `case_id` must be unique within the file.
- `question` already contains the user's question and goes to both judges.
- `dialect` and `context` are optional. Add existing schema facts or business definitions when useful; no extra semantic layer is required.
- Each result needs `columns`, positional `rows`, and `total_rows`.
- `total_rows` is the **complete query output count**, including any SQL-level limit. If a query returns 1,200 rows and the preview contains 50, use `total_rows: 1200`.
- Supply up to 50 preview rows per result. If more are supplied, the judges and HTML report still use only the first 50.

See [`examples/cases.jsonl`](../examples/cases.jsonl) for more records and the [API reference](api.md#queryresult) for validation and execution-error records.

## 4. Run the three metrics

Set credentials in your shell and select a model that supports strict JSON-schema structured output:

```bash
export OPENAI_API_KEY="your-api-key"
export OPENAI_MODEL="your-structured-output-model"

bash scripts/eval.sh eval --input cases.jsonl
```

The helper does not load `.env` files. Use exported environment variables or the model options supported by the evaluation command.

This calculates row-count matching and makes two separate LLM judge calls per successful case, before provider-managed retries. It writes:

```text
reports/evaluation.json    Scores, explanations, metadata, and summary
reports/evaluation.html    Interactive report with SQL and sampled data
```

Open `reports/evaluation.html` to review the run. The HTML is complete and works offline.

To use a different model or output location:

```bash
bash scripts/eval.sh eval \
  --input cases.jsonl \
  --output reports/customer-sales.json \
  --model "$OPENAI_MODEL" \
  --concurrency 4
```

This also creates `reports/customer-sales.html`. Use `--html-output` to choose a separate HTML destination. The helper forwards the evaluation CLI's options; list them with:

```bash
bash scripts/eval.sh eval --help
```

## 5. Generate HTML from saved results

If you already have evaluation JSON, do not rerun the judges just to create HTML:

```bash
bash scripts/eval.sh report \
  --cases cases.jsonl \
  --results reports/evaluation.json
```

This writes `reports/evaluation.html` without API credentials or model calls. Choose another destination with `--output`:

```bash
bash scripts/eval.sh report \
  --cases cases.jsonl \
  --results reports/evaluation.json \
  --output reports/review.html
```

Keep the original cases file with each evaluation. The saved score JSON does not include questions, SQL, or result rows. The exporter joins the files by `case_id`, checks matching unique IDs, and verifies the summary. An ID match cannot establish that a changed cases file contains the original execution evidence.

## Paths, outcomes, and troubleshooting

Default outputs go into this repository's `reports/` directory. Paths you explicitly provide are relative to your current working directory. You can invoke the helper by its absolute path from another directory. Input and output paths must be distinct.

| Exit code | Meaning |
| --- | --- |
| `0` | Completed successfully. Confirmed `FAIL` and unresolved `REVIEW` are valid evaluation outcomes. |
| `1` | Evaluation reports were saved, but at least one metric has an operational `ERROR`. Inspect the report. |
| `2` | Input, configuration, setup, or report writing failed. Read the message and fix the cause. |

Saved-report export returns `0` for a valid report even when the stored scores contain `ERROR`. If evaluation saved JSON but could not write HTML, use the `report` command to retry HTML generation.

If the environment is missing, run `bash scripts/eval.sh setup`. If a judge cannot be configured, check the API key, model name, endpoint, and strict structured-output support. If an input contains only questions and target SQL, complete step 3 before running evaluation.

Use `bash scripts/eval.sh --help` for the workflow overview. For definitions and interpretation, read [the judging guide](judging.md) and [the HTML report guide](html-reports.md).
