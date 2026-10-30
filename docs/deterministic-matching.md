# Deterministic dataset matching

Compare two complete datasets without SQL execution, an API key, or an LLM. The comparator accepts pandas DataFrames or ordinary Python datasets. It ignores column names, column order, DataFrame indexes, and row order. There is no essential-column configuration.

The comparator uses **multisets**, which preserve repeated values and repeated rows. It finds a maximum one-to-one matching of row occurrences. One generated occurrence cannot satisfy two target occurrences.

This is a configurable **value-compatibility check**. It does not establish that values have the same business roles or that SQL answers the question. With bidirectional row matching enabled, a generated query that omits a required measure can be accepted if its remaining values match. Keep the existing SQL-semantic evaluation when that distinction matters. The new comparator is separate from the existing three-score evaluation and HTML reports.

## Run the JSON comparison

From a checkout, install the locked runtime dependencies once:

```bash
bash scripts/eval.sh setup
```

Then compare the included complete example datasets:

```bash
uv run --locked --no-sync text2sql-eval-match \
  --target examples/matching-target.json \
  --generated examples/matching-generated.json
```

The result is written as JSON to standard output. Save it atomically with `--output`:

```bash
uv run --locked --no-sync text2sql-eval-match \
  --target examples/matching-target.json \
  --generated examples/matching-generated.json \
  --output reports/dataset-comparison.json
```

Equivalent Python entry points, using the installed project environment, are:

```bash
uv run --locked --no-sync python -m text2sql_eval.match_cli \
  --target examples/matching-target.json \
  --generated examples/matching-generated.json

uv run --locked --no-sync python scripts/compare_datasets.py \
  --target examples/matching-target.json \
  --generated examples/matching-generated.json
```

The script is a thin entry point; it does not install dependencies or load environment files. No model credentials are needed.

| Exit code | Meaning |
| --- | --- |
| `0` | Accepted under the selected policies. |
| `1` | Valid comparison, rejected under the selected policies. The result is still written. |
| `2` | Invalid input or configuration, resource limit, or output failure. No valid decision was produced. |

An output file cannot overwrite either input, including through a symlink or hard link. Comparing an input file with itself is allowed.

## Python API

```python
from text2sql_eval.matching import MatchingConfig, compare_datasets, compare_rows

target = [[1, 100], [2, 200]]
generated = [[200, "Bob", 2], [100, "Ada", 1]]

result = compare_datasets(target, generated)
assert result.accepted
assert result.matched_row_count == 2
print(result.model_dump_json(indent=2))

row = compare_rows(["Alice", 30], [30, "Alice", "NY"])
assert row.accepted
assert row.relation == "target_subset"

subset = compare_datasets([[1]], [[1], [2]])
assert subset.accepted
assert subset.relation == "target_subset"

stricter = compare_datasets(
    target,
    generated,
    config=MatchingConfig(row_policy="target_subset", dataset_policy="equal"),
)
```

Run [`examples/compare_datasets.py`](../examples/compare_datasets.py) for a complete API example.

### DataFrames

Install pandas support if your application does not already have pandas:

```bash
uv sync --locked --extra dataframes
```

Then pass DataFrames directly:

```python
import pandas as pd
from text2sql_eval.matching import compare_datasets

target = pd.DataFrame([[1, 100], [2, 200]], columns=["customer_id", "sales"])
generated = pd.DataFrame(
    [[200, "Bob", 2], [100, "Ada", 1]],
    columns=["revenue", "name", "client_id"],
)
result = compare_datasets(target, generated)
assert result.accepted
```

Labels may differ or repeat; they do not participate in matching. Returned row indexes refer to zero-based row positions, not the DataFrame index labels.

### Dataset formats

The Python API and JSON CLI accept rectangular row arrays:

```json
[[1, 100], [2, 200]]
```

They also accept positional records with column metadata:

```json
{
  "columns": ["customer_id", "total_sales"],
  "rows": [[1, 100], [2, 200]],
  "total_rows": 2
}
```

`total_rows` is optional in this format. When present, it must equal the number of supplied rows. A first-50-row preview with `total_rows: 1200` is rejected. Failed executions are rejected. Successful, complete `QueryResult` objects are accepted through the Python API.

Record objects are also supported:

```json
[
  {"customer_id": 1, "total_sales": 100},
  {"customer_id": 2, "total_sales": 200}
]
```

Every record in one dataset must have the same keys. Keys establish the tabular shape, but their names do not determine value matches. Each dataset can have a different number of columns. Ragged rows and mixed row formats are invalid. Use an empty array `[]` for an empty dataset.

Bare datasets have no completeness metadata, so the caller is responsible for providing all rows. The comparator never applies a 50-row cap. JSON files must be valid JSON: use `null`, not `NaN` or `Infinity`; duplicate object keys are rejected because they would otherwise discard values.

## Configure the two levels independently

`MatchingConfig` has separate `row_policy` and `dataset_policy` fields. Both use the following names, with different units:

| Policy | Within each row: `row_policy` | Across rows: `dataset_policy` |
| --- | --- | --- |
| `equal` | Both rows contain exactly the same value multiset. | Every target and generated row occurrence must be matched. |
| `target_subset` | Every target value occurrence is present in the generated row. | Every target row occurrence must be matched; extra generated occurrences are allowed. |
| `generated_subset` | Every generated value occurrence is present in the target row. | Every generated row occurrence must be matched; extra target occurrences are allowed. |
| `bidirectional` | Either within-row containment direction is allowed. | Either complete across-row containment direction is allowed. |

Equality is accepted by both directional subset policies. The defaults are:

```python
MatchingConfig(
    row_policy="bidirectional",
    dataset_policy="bidirectional",
    max_candidate_edges=1_000_000,
)
```

Bidirectional containment is enabled at both levels by default. One dataset must be fully matched to distinct row occurrences in the other; their counts may differ. To require equal row counts and complete matching of both datasets while retaining bidirectional row subsets:

```bash
uv run --locked --no-sync text2sql-eval-match \
  --target target.json \
  --generated generated.json \
  --row-policy bidirectional \
  --dataset-policy equal
```

For exact value agreement at both levels, use `--row-policy equal --dataset-policy equal`. To reject generated rows that omit target values, use `--row-policy target_subset`. These options do not introduce a field mapping or essential-column list.

An empty dataset is a subset of every dataset. The default `dataset_policy="bidirectional"` therefore accepts an empty/nonempty comparison and reports its direction and zero matched rows. Select `dataset_policy="equal"` to reject differing row counts. These outcomes follow the configured containment rule.

## Read the outcome

`accepted` is the decision under the selected policies. The result includes its configuration so the decision can be reproduced and interpreted.

The dataset `relation` describes coverage **under the configured row policy**:

| Relation | Meaning |
| --- | --- |
| `full_match` | Every occurrence in both datasets has a matching partner. This does not require identical row values when subset row policies are allowed. |
| `target_subset` | Every target occurrence is matched; some generated occurrences remain. |
| `generated_subset` | Every generated occurrence is matched; some target occurrences remain. |
| `partial_overlap` | Some occurrences match, but neither dataset is fully covered. |
| `no_match` | No row pairs are compatible under the configured row policy. |

`full_match` deliberately does not claim mathematical equality of the original datasets. For example, every generated row can contain additional values. Conversely, `no_match` under `row_policy="equal"` does not mean the rows have no values in common; it means the policy permits no matched pairs.

Each item in `matches` contains `target_index`, `generated_index`, and the actual within-row `relation`: `equal`, `target_subset`, or `generated_subset`. `row_relation_counts` summarizes those matched directions. The row helper additionally returns `incompatible` for rows where neither containment direction holds, while preserving the actual relation even when a policy rejects it.

The result also includes:

- Complete target, generated, and matched row counts.
- `row_count_match`, independent of the selected acceptance policy.
- Unmatched target and generated row positions.
- `target_coverage` = matched / target occurrences.
- `generated_coverage` = matched / generated occurrences.
- `f1` = 2 × matched / (target occurrences + generated occurrences).
- A concise decision reason.

An empty denominator produces `null` for its coverage. Both datasets empty have `f1: 1.0` and `full_match`. For equal nonzero row counts, both coverage values and F1 are identical. A high partial score does not override the configured acceptance rule.

If several maximum matchings exist, the implementation produces a reproducible result for the same inputs and installed dependencies. Do not rely on identical index-pair choices across library versions. Counts and acceptance are the important outcome.

## Value rules and scale

Integer `1`, floating-point `1.0`, and `Decimal("1")` are equivalent numeric values. Boolean `True` is distinct from numeric `1`; string `"1"` is also distinct. Missing values (`None`, floating NaN, pandas `NA` and `NaT`) share one null representation. Null is not a wildcard and does not equal zero or an empty string.

The JSON CLI parses decimal numbers as `Decimal`, preserving long decimal values such as `0.1000000000000000000001` instead of collapsing them to `0.1`. Python floating-point inputs are normalized through their string representation; precision lost before the comparison cannot be recovered. Use `Decimal` inputs when exact decimal precision is required.

There is no automatic string trimming, case folding, unit conversion, numeric tolerance, rounding, or timezone conversion. Nested array cells retain their internal order; ignoring column order does not reorder values inside an array. Unsupported cell objects are rejected instead of compared through their string representation.

Python date, datetime, time, and bytes values retain their types. A date string loaded from JSON is not automatically converted into a datetime value from a DataFrame. Convert values explicitly before comparison when both datasets should use the same representation. Convert non-missing `numpy.datetime64` cells to Python datetimes or pandas timestamps first.

Repeated cells retain their counts: `[1, 1]` is not contained in `[1, 999]`. Repeated rows also retain their counts. The matcher does not greedily consume row partners; it computes a maximum matching so that an early choice cannot unnecessarily reduce the matched count.

For equally wide tables, row-value containment reduces to exact multiset equality, allowing a counting fast path. For different widths, identical row signatures are grouped, candidate partners are indexed by values, and a capacitated maximum-flow calculation matches grouped occurrence counts. This avoids constructing an edge for every pair of duplicate occurrences.

Distinct-row compatibility can still be dense. `max_candidate_edges` limits that graph; exceeding the limit returns an actionable error, never an automatic rejection or a partial decision. Increase the limit deliberately with `--max-candidate-edges` when resources allow. The complete datasets, signatures, and output match indexes are held in memory; this is not a streaming or distributed comparator.

The matching algorithm uses [SciPy's maximum-flow implementation](https://docs.scipy.org/doc/scipy/reference/generated/scipy.sparse.csgraph.maximum_flow.html). DataFrame iteration and missing-value detection follow [pandas `itertuples`](https://pandas.pydata.org/docs/reference/api/pandas.DataFrame.itertuples.html) and [`isna`](https://pandas.pydata.org/docs/reference/api/pandas.isna.html).
