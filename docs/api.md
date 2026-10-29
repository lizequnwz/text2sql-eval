# Python API reference

Import the public API from `text2sql_eval`. Models use Pydantic 2 with strict validation and reject unknown fields. Input mistakes are rejected before scoring; they are not silently repaired.

## `QueryResult`

```python
QueryResult(
    columns: list[str],
    rows: list[list[JsonValue]],
    total_rows: int | None,
    execution_error: str | None = None,
)
```

Represents a query your application has already executed.

| Field | Meaning |
| --- | --- |
| `columns` | Output labels, in the same order as each positional row. |
| `rows` | Available result preview. The first 50 rows are sent to the sampled judge. |
| `total_rows` | Count of the complete query output, not the preview length. Required even when null. |
| `execution_error` | Nonempty description of a failed query or failed SQL generation. |

A successful result requires a nonnegative `total_rows`, at least one column label, and exactly one cell per column in each row. A preview cannot contain more rows than `total_rows`. Empty successful results still need column labels and `total_rows=0`.

A failed result requires `execution_error`, `total_rows=None`, and no rows. Repeated column labels are preserved; dictionary-shaped rows are not accepted. Nested JSON is supported. Convert database-specific values such as dates or decimals explicitly. Non-finite numbers are rejected.

The evaluator does not verify that caller-supplied counts or previews actually came from the accompanying SQL. Your execution pipeline must maintain that association.

## `EvaluationCase`

```python
EvaluationCase(
    case_id: str,
    question: str,
    target_sql: str,
    generated_sql: str,
    target_result: QueryResult,
    generated_result: QueryResult,
    dialect: str | None = None,
    context: str | None = None,
)
```

`case_id`, `question`, and `target_sql` must contain text. The reference result must represent a successful execution. An empty or whitespace-only `generated_sql` is permitted only when `generated_result` records an explicit failure.

Use `dialect` to identify the SQL dialect when known. `context` can contain existing schema facts, metric definitions, output requirements, or evaluation assumptions. It is sent to both judges. Do not put preview-only evidence in this field if you want the SQL judge to remain independent of execution data.

To load a JSON record:

```python
case = EvaluationCase.model_validate_json(json_record)
```

Unknown fields, inconsistent dimensions, wrong input types, and invalid gold raise Pydantic validation errors. Successful row counts are not inferred from a preview.

Scoring methods revalidate input snapshots, including nested result records. Batch methods validate every case before making judge requests, so an invalid case is not discovered only after earlier paid calls.

## `JudgeDecision`

```python
JudgeDecision(
    verdict: Literal["PASS", "FAIL"],
    reason: str,
    needs_review: bool,
    evidence: list[str],
)
```

The response schema passed to `ChatOpenAI.with_structured_output()`. All fields are required. `reason` must contain text; whitespace-only explanations are rejected. `evidence` should cite relevant clauses, observed facts, or missing information without exposing private reasoning.

`needs_review=True` overrides either provisional binary verdict. The resulting metric status is `REVIEW` and its numeric score is `None`. Read the normalized `MetricResult.status` when making downstream decisions, rather than using `judgment.verdict` alone.

## `Evaluator`

```python
Evaluator(llm: ChatOpenAI)
```

Accepts a caller-configured LangChain `ChatOpenAI` instance. Set model, credentials, endpoint, retries, timeout, and any model-specific settings there.

```python
llm = ChatOpenAI(model=model_name, timeout=60, max_retries=2)
evaluator = Evaluator(llm)
```

The evaluator binds `JudgeDecision` with `method="json_schema"`, `strict=True`, and `include_raw=True`. The provider and selected model must support that format. The evaluator has no tools, database connection, conversation history, or memory shared between judge calls.

### `evaluate(case) -> CaseScores`

Runs row-count matching and the two LLM judges. The sampled and semantic requests are separate. A failure in one request does not prevent the other judge from running. Synchronous requests run sequentially.

Normally this makes two LLM requests, before any provider-managed retries.

### `evaluate_many(cases) -> list[CaseScores]`

Scores a sequence in input order. Duplicate `case_id` values are rejected before any judge request. This method runs cases sequentially.

### `await aevaluate(case) -> CaseScores`

Runs the two independent judge requests concurrently. Cancellation is not converted into a metric correctness verdict.

### `await aevaluate_many(cases, *, concurrency=4) -> list[CaseScores]`

Bounds the number of active cases with a semaphore and returns results in input order. Each active case can make two concurrent requests. `concurrency` must be a positive integer; booleans are rejected.

Use this method inside an existing event loop. In a synchronous script, wrap it with `asyncio.run()`.

### Generated-query failure behavior

| Input condition | Row count | Sampled result | SQL semantics |
| --- | --- | --- | --- |
| Successful generated execution | Compare counts | Invoke judge | Invoke judge |
| Generated execution failed, SQL is present | `ERROR` | `ERROR`, no request | Invoke judge without execution evidence |
| Generation failed, SQL is empty | `ERROR` | `ERROR`, no request | `ERROR`, no request |

An operational failure is not treated as an empty successful result. A semantic pass on SQL whose execution failed remains only a semantic judgment; it does not make the complete case successful.

### Judge failures

Provider exceptions, refusals or empty parsed output, and schema validation failures produce `ERROR` for the affected metric. Other metric results are retained. Error reports include an exception class or parsing category, rather than copying provider request bodies or input execution-error text.

Provider retry behavior belongs to `ChatOpenAI`. There is no extra package-level retry loop that converts repeated failures into a SQL verdict.

## `score_row_count(case) -> MetricResult`

A standalone deterministic function with no model invocation:

```python
from text2sql_eval import score_row_count

score = score_row_count(case)
assert score.status in {"PASS", "FAIL", "ERROR"}
```

Compares `target_result.total_rows` with `generated_result.total_rows`. It does not compare values or column counts, and does not use preview lengths. An explicit generated execution failure produces `ERROR`.

Row-count equality is diagnostic. For example, two `COUNT(*)` queries can each return one row while containing different count values.

## `CaseScores` and `MetricResult`

`CaseScores` contains:

```text
case_id
row_count_match
sampled_result_consistency
sql_semantic
```

Each metric is a `MetricResult`:

| Field | Meaning |
| --- | --- |
| `name` | One of the three metric keys. |
| `status` | `PASS`, `FAIL`, `REVIEW`, or `ERROR`. |
| `score` | Computed `1`, `0`, or `None`; also included in serialization. |
| `reason` | Explanation or operational failure description. |
| `judgment` | Validated `JudgeDecision` for a parsed LLM response; otherwise `None`. |
| `metadata` | Judge model name, prompt fingerprint, elapsed seconds, and available token counts. |
| `error_type` | Error category when applicable; otherwise `None`. |

`JudgeMetadata.token_usage`, when available, contains provider-supplied `input_tokens`, `output_tokens`, and `total_tokens`. Missing usage data is not treated as zero usage.

Serialize using standard Pydantic methods:

```python
as_dict = result.model_dump(mode="json")
as_json = result.model_dump_json(indent=2)
```

Reload a saved case result with `CaseScores.model_validate_json(as_json)`. Scores are derived from status; an inconsistent supplied score or a status that ignores `needs_review` is rejected.

## `summarize(results) -> dict[MetricName, MetricSummary]`

Aggregates a sequence of `CaseScores`. Duplicate case IDs are rejected to prevent accidental double counting. The denominator is the number of supplied cases for every metric.

`MetricSummary` contains:

| Field | Definition |
| --- | --- |
| `cases` | Fixed number of supplied cases, `N`. |
| `passed` | Number of confirmed `PASS` outcomes. |
| `failed` | Number of confirmed `FAIL` outcomes. |
| `review` | Number of unresolved `REVIEW` outcomes. |
| `errors` | Number of operational `ERROR` outcomes. |
| `pass_rate` | `passed / N`, or `None` when `N` is zero. |
| `decision_coverage` | `(passed + failed) / N`, or `None` when `N` is zero. |

For example, 6 passes, 2 failures, 1 review, and 1 error give a pass rate of `0.6` and decision coverage of `0.8`. Excluding the unresolved cases would change the denominator and overstate automatic pass coverage.

Keep the three metric summaries separate. The package does not generate a combined accuracy number or an overall release decision.

## Prompt inspection

The prompt helpers live in `text2sql_eval.prompts`:

```python
from text2sql_eval.prompts import (
    build_sampled_messages,
    build_semantic_messages,
    prompt_sha256,
    system_prompt,
)

sampled_messages = build_sampled_messages(case)
semantic_messages = build_semantic_messages(case)
rubric = system_prompt("sql_semantic")
fingerprint = prompt_sha256("sql_semantic")
```

Each message list contains a system rubric and a JSON-encoded human message. Sampled payloads contain `target_result` and `generated_result`, each with `columns`, up to 50 `rows`, `total_rows`, `provided_rows`, `shown_rows`, `truncated`, and `execution_error`. The original case is not mutated.

Semantic payloads explicitly include only `question`, `target_sql`, `generated_sql`, `dialect`, and `context`. They do not copy the result objects or the other judge's decision.

`system_prompt()` combines `common.md` with the selected metric-specific resource. `prompt_sha256()` fingerprints those exact combined system instructions. The fingerprint excludes the case payload, model settings, and output schema.

An `Evaluator` captures its prompt text and fingerprints at construction. Create a new evaluator after changing prompt resources; existing evaluators continue using their captured instructions.

See [the judging guide](judging.md) for the decision criteria, examples, and calibration guidance.
