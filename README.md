# text2sql-eval

Three separate scores for text-to-SQL predictions, using results your application has already executed:

1. **Row Count Match Rate** — compare complete result row counts.
2. **Sampled Result Consistency Rate** — judge up to 50 rows from each result, with both SQL queries as context.
3. **SQL Semantic Pass Rate** — judge the generated SQL against the question and reference SQL in a separate call.

The two LLM judges use LangChain's `ChatOpenAI.with_structured_output()` with a validated Pydantic response. Each returns a binary verdict, a reason, evidence, and a review flag. Uncertainty and provider errors remain visible in the report.

This package accepts pre-executed query results. It does not connect to a database or execute SQL.

Each evaluation writes a JSON report and a standalone interactive HTML report. The HTML lets you inspect questions, SQL, result previews, and judge evidence without another model call.

## What each score means

| Metric key | A confirmed PASS means | What it does not establish |
| --- | --- | --- |
| `row_count_match` | The complete output row counts are equal. | That the values, records, or SQL logic are correct. |
| `sampled_result_consistency` | No material contradiction was found in the supplied evidence. | That every row in the complete results matches. |
| `sql_semantic` | The judge considers the generated SQL to satisfy the question's requirements. | A formal proof of SQL equivalence or correctness. |

The sampled judge can allow supplementary columns, incidental row ordering, and permitted permutations within ties. It must still check differences that affect which records are selected, such as `ORDER BY ... LIMIT`, ranking, and window calculations. It cannot assume that an unseen tie explains every mismatch.

The semantic judge receives the question and SQL context, but no execution rows, row counts, or sampled judge decision. This keeps matching preview data from anchoring its logic assessment. Both judges can still make the same mistake; their agreement is supporting evidence, not independent proof.

These are explicit application metrics. The sampled metric is not full-result Execution Accuracy and is not directly comparable to an official BIRD or Spider score. See [the judging guide](docs/judging.md) for the complete rubric and limitations.

## Install

Python 3.11 or later is required.

For development, clone the repository and install the locked dependencies with [uv](https://docs.astral.sh/uv/):

```bash
git clone https://github.com/lizequnwz/text2sql-eval.git
cd text2sql-eval
uv sync --locked
```

For an application that only needs the package:

```bash
python -m pip install .
```

Or install directly from GitHub:

```bash
python -m pip install "git+https://github.com/lizequnwz/text2sql-eval.git"
```

The runtime dependencies are `langchain-openai`, `langchain-core`, and Pydantic 2. The package does not require an agent framework, database driver, or vector store.

## Configure the judge

Choose a model and endpoint that support strict JSON-schema structured output. The package does not select a model for you.

```bash
export OPENAI_API_KEY="your-api-key"
export OPENAI_MODEL="your-structured-output-model"
```

For a compatible endpoint, you can also set `OPENAI_BASE_URL` or pass `--base-url`. Compatibility with the OpenAI request format alone does not guarantee support for strict structured output.

`.env.example` lists the supported environment variables. The package does not automatically load `.env` files. API keys are read by `ChatOpenAI`; never put them in an evaluation case or commit them.

No temperature is imposed by default. If your selected model supports temperature control, you can configure it on `ChatOpenAI` or use `--temperature`.

## Run from the command line

The input is JSONL: one complete evaluation case per line. Blank lines are ignored. Every case is validated, including unique `case_id` values, before evaluation starts.

```bash
uv run text2sql-eval \
  --input examples/cases.jsonl \
  --output reports/evaluation.json
```

The module entry point is equivalent:

```bash
uv run python -m text2sql_eval \
  --input examples/cases.jsonl \
  --output reports/evaluation.json \
  --model "$OPENAI_MODEL" \
  --concurrency 4 \
  --timeout 60 \
  --max-retries 2
```

`--concurrency` bounds active cases. Each case can make two concurrent LLM requests, so `--concurrency 4` can produce up to eight in-flight requests. Timeouts and retries are passed to `ChatOpenAI`.

The JSON report contains `package_version`, per-case `results`, and a separate `summary` for each metric. The command also creates `reports/evaluation.html` beside it. Use `--html-output` to choose a different HTML path:

```bash
uv run text2sql-eval \
  --input examples/cases.jsonl \
  --output reports/evaluation.json \
  --html-output reports/review.html
```

The output paths must be distinct from one another and from the input. They are checked before model requests. JSON is written first; if HTML export fails, the completed JSON report is preserved and the command exits with code `2`.

| Exit code | Meaning |
| --- | --- |
| `0` | Evaluation completed with no metric `ERROR`. `FAIL` and `REVIEW` are valid evaluation outcomes. |
| `1` | Both reports were written, but at least one metric has status `ERROR`. |
| `2` | Input, configuration, or report writing failed. A completed JSON report can remain if HTML writing fails. |

Run `uv run text2sql-eval --help` for all options.

## Inspect or export an HTML report

Open the generated HTML file in a browser. It is a single offline file with no CDN or JavaScript framework. It provides:

- Three summary cards for the complete run, using the fixed evaluation denominator.
- Search, metric/status filters, and a filter for confirmed PASS-versus-FAIL disagreement between the two judges.
- A sortable case table with 25 cases per page.
- Expandable questions, side-by-side SQL, independent result previews, and judge reasons, evidence, and metadata.
- Light/dark themes, keyboard controls, and a print layout.

Filters change the visible case list; they do not recompute whole-run summary rates. Each query preview contains at most 50 rows, with its full row count and truncation state shown separately.

You can create HTML from an existing JSON report without credentials, SQL execution, or LLM calls:

```bash
uv run text2sql-eval-report \
  --cases examples/cases.jsonl \
  --results reports/evaluation.json \
  --output reports/evaluation.html
```

Keep the original cases file. The JSON scoring report does not store questions, SQL, or query previews. The exporter joins cases and scores by `case_id`, requires unique matching ID sets, preserves the saved score order, and checks saved summaries against the actual metric statuses. It cannot verify that a supplied case is the original execution evidence based on its ID alone.

The exporter exits `0` when it writes the report, including reports that contain stored `ERROR` scores. Invalid input or a writing failure returns `2`.

To explore the interface with fabricated data and no model setup:

```bash
uv run python examples/html_report.py --output reports/demo.html
```

The demo creates 36 clearly labeled synthetic cases and canned judge decisions. It is a report demonstration, not an evaluation run or evidence of judge accuracy.

HTML reports contain the supplied SQL and up to 50 result rows per query. Share them with the same care as those inputs. See [the HTML report guide](docs/html-reports.md) for export and interpretation details.

## Use the Python API

```python
import os

from langchain_openai import ChatOpenAI

from text2sql_eval import EvaluationCase, Evaluator, QueryResult, summarize

case = EvaluationCase(
    case_id="customer-sales-001",
    question="What is the total sales amount for each customer?",
    target_sql=("SELECT customer_id, SUM(amount) AS total_sales FROM orders GROUP BY customer_id"),
    generated_sql=(
        "SELECT o.customer_id, c.customer_name, SUM(o.amount) AS total_sales "
        "FROM orders o JOIN customers c ON c.customer_id = o.customer_id "
        "GROUP BY o.customer_id, c.customer_name ORDER BY total_sales DESC"
    ),
    target_result=QueryResult(
        columns=["customer_id", "total_sales"],
        rows=[[1, 100], [2, 200]],
        total_rows=2,
    ),
    generated_result=QueryResult(
        columns=["customer_id", "customer_name", "total_sales"],
        rows=[[2, "Bob", 200], [1, "Ada", 100]],
        total_rows=2,
    ),
    dialect="postgresql",
    context=(
        "customers.customer_id is unique. Every order has a matching customer. "
        "customer_name is supplementary information. No display order is required."
    ),
)

llm = ChatOpenAI(
    model=os.environ["OPENAI_MODEL"],
    timeout=60,
    max_retries=2,
)
evaluator = Evaluator(llm)

result = evaluator.evaluate(case)
print(result.model_dump_json(indent=2))
print(summarize([result])["sampled_result_consistency"].model_dump())
```

The optional `context` field reuses schema facts or business definitions you already have. The judge is instructed to flag missing information for review, rather than invent business rules.

For batches, use `evaluator.evaluate_many(cases)`. For an asynchronous application:

```python
results = await evaluator.aevaluate_many(cases, concurrency=4)
summary = summarize(results)
```

`aevaluate()` runs both judge calls concurrently. Batch methods preserve input order. See [the API reference](docs/api.md) and [the Python example](examples/evaluate.py).

To write an HTML report from Python after scoring:

```python
from text2sql_eval import write_html_report

results = evaluator.evaluate_many(cases)
path = write_html_report(cases, results, "reports/evaluation.html")
print(path)
```

## Input contract

Each case contains `case_id`, `question`, `target_sql`, `generated_sql`, `target_result`, and `generated_result`. `dialect` and `context` are optional strings.

Each successful query result contains:

```json
{
  "columns": ["customer_id", "total_sales"],
  "rows": [[1, 100], [2, 200]],
  "total_rows": 1200
}
```

`total_rows` is the count of the **complete executed output**, including any SQL-level `LIMIT`. It must not be the preview length when more rows exist. `rows` should contain the first available rows in their returned order. The sampled judge receives no more than the first 50 supplied rows; metadata records how many were supplied, shown, and whether the preview is incomplete.

Use positional rows, with one cell per column. This preserves data even when SQL returns repeated column labels. JSON values, including nested JSON, are accepted. Convert dates and decimals explicitly before constructing a case, preserving the units and precision relevant to the question. NaN and infinity are rejected.

A generated query failure is explicit:

```json
{
  "columns": [],
  "rows": [],
  "total_rows": null,
  "execution_error": "SQL execution failed"
}
```

That produces `ERROR` for row-count and sampled-result metrics instead of treating the failure as an empty answer. If generated SQL exists, the semantic judge still assesses its logic independently. If generation failed, use an empty `generated_sql` with an explicit error; all three metrics then report `ERROR` without judge requests.

A failed target execution is invalid gold and is rejected during input validation. Fix or remove invalid gold before defining the eligible evaluation set. Use the same data snapshot, role, time zone, and date basis for the two executions.

## Structured decisions and rates

The model is bound with:

```python
llm.with_structured_output(
    JudgeDecision,
    method="json_schema",
    strict=True,
    include_raw=True,
)
```

All four decision fields are required:

```json
{
  "verdict": "PASS",
  "reason": "The required totals agree; the extra name column is supplementary.",
  "needs_review": false,
  "evidence": ["Both previews contain customer 1 with total_sales = 100."]
}
```

The normalized `MetricResult.status` is authoritative:

| Status | Numeric `score` | Interpretation |
| --- | --- | --- |
| `PASS` | `1` | Confirmed pass under this metric's rubric. |
| `FAIL` | `0` | Confirmed failure under this metric's rubric. |
| `REVIEW` | `null` | `needs_review` is true; the binary verdict is provisional and is not counted. |
| `ERROR` | `null` | Execution or judge operation failed; no correctness verdict was made. |

For each metric, with a fixed eligible set of `N` cases:

```text
pass_rate = confirmed PASS cases / N
decision_coverage = (PASS cases + FAIL cases) / N
```

`REVIEW` and `ERROR` remain in the denominator. Their counts are reported separately; neither is relabeled as a confirmed SQL failure. Rates are fractions from 0 to 1. An empty set has undefined rates, represented as `null`.

Do not average the three scores. A missing date filter can pass row counts and preview consistency on today's data but fail SQL semantics.

In this project, **positive means the evaluator flags SQL as wrong**. A false positive rejects correct SQL. A false negative accepts incorrect SQL. A row-count mismatch remains a diagnostic and does not by itself prove the SQL is wrong.

## Prompts and reproducibility

The packaged system instructions are readable Markdown:

- [Shared rules](src/text2sql_eval/prompts/common.md)
- [Sampled result rubric](src/text2sql_eval/prompts/sampled_result_consistency.md)
- [SQL semantic rubric](src/text2sql_eval/prompts/sql_semantics.md)

Each LLM metric records the configured model name, a SHA-256 fingerprint of its combined system instructions, elapsed time, and token usage when the provider supplies it. Keep your input dataset, execution conditions, package revision, model configuration, and report together when comparing runs. A prompt fingerprint does not identify the dataset or guarantee model determinism.

To change the rubric, edit the relevant prompt resources and rebuild or reinstall the package. Create a new `Evaluator` after changes: each evaluator captures its instructions and fingerprints at construction. There is no runtime prompt-template configuration API.

Model-bound inputs contain SQL and, for the sampled judge, result previews. Include only data you intend to send to the configured provider. Prompts instruct the judges to treat SQL comments and cell contents as untrusted evidence, not instructions. Provider failures, refusals, and invalid structured responses become metric `ERROR` records; they do not silently pass or fail SQL. Exception class names are recorded without copying provider request bodies into reports.

## Development

```bash
uv sync --locked
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv build
```

The test suite uses offline recording models. It checks routing, judge isolation, truncation, uncertainty, failure handling, and fixed denominators without API keys or paid LLM requests. These checks establish package behavior, not judge accuracy. Review a human-labeled sample of your own ordering, tie, extra-column, and logic-error cases before claiming a reduction in false positives or false negatives.

Optional report interaction checks use Node.js 26 or later and jsdom:

```bash
npm ci
npm run test:report
```

This generates the synthetic demonstration and checks search, filtering, sorting, pagination, details, keyboard focus, themes, and safe text rendering without a browser or network requests. It does not perform browser layout or screenshot tests. Node.js is not required to install the Python package or read generated reports.

## Further reading

- [API reference](docs/api.md)
- [Judging guide](docs/judging.md)
- [HTML report guide](docs/html-reports.md)
- [LangChain structured output reference](https://reference.langchain.com/python/langchain-openai/chat_models/base/ChatOpenAI/with_structured_output)
- [FLEX: Expert-level False-Less EXecution Metric, NAACL 2025](https://aclanthology.org/2025.naacl-long.228.pdf)
- [PostgreSQL LIMIT and OFFSET](https://www.postgresql.org/docs/current/queries-limit.html)

FLEX motivates context-aware SQL evaluation and different handling of matching and differing results. It does not validate this package's exact two-judge, first-50-row protocol.

## License

[MIT](LICENSE).
