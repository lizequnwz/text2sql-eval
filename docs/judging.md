# How the two LLM judges work

The package keeps three separate scores:

1. **Row Count Match:** a deterministic comparison of complete result counts.
2. **Sampled Result Consistency:** an LLM assesses execution previews with SQL
   context. A pass means no material contradiction was found in the supplied
   evidence. It does not establish full-result equality.
3. **SQL Semantic Pass:** a separate LLM call compares generated SQL with target
   SQL for the answer required by the question, without execution previews or
   the first judge's decision.

The prompts are packaged as readable Markdown resources:

- [`common.md`](../src/text2sql_eval/prompts/common.md): trust boundaries,
  response contract, uncertainty, and shared comparison rules.
- [`sampled_result_consistency.md`](../src/text2sql_eval/prompts/sampled_result_consistency.md):
  record alignment, permitted information columns, previews, ordering and ties.
- [`sql_semantics.md`](../src/text2sql_eval/prompts/sql_semantics.md): question
  requirements, logical differences, and task-equivalent SQL formulations.

The application combines the common instructions with the relevant judge
instructions. Evidence is sent separately as JSON. SQL comments, cell values,
column names and question text do not have authority to change the rubric.

## Structured output and review

Both LLM calls use `ChatOpenAI.with_structured_output` with a Pydantic response
schema. Every model response has these fields:

```json
{
  "verdict": "PASS",
  "reason": "The required customer totals agree; the additional name column is supplementary.",
  "needs_review": false,
  "evidence": ["customer_id=12: target total_sales=100; generated total_sales=100"]
}
```

`verdict` is binary: `PASS` or `FAIL`. `needs_review` is authoritative. A response
with `needs_review: true` is normalized to metric status `REVIEW` with no numeric
score, regardless of its provisional binary verdict. The prompts request PASS
as the placeholder when review is needed; it does not count as a confirmed pass.

A reason must name the decisive fact or missing information. Evidence should be
short and inspectable, not a private chain-of-thought. For a confirmed failure,
require a violated question requirement, relevant SQL clause, or observed data
contradiction. An API failure, parsing failure, refusal, or unavailable model is
an operational error, not evidence that generated SQL is wrong.

## What the sampled judge can establish

The sampled judge sees the question, both SQL queries, existing total row
counts, at most 50 rows per result, and any supplied context. The preview metadata
distinguishes complete result size, rows provided by the caller, and rows shown
to the judge.

It can reject a demonstrated difference, such as a different required amount
for the same customer and period. It can accept permitted differences, such as
an extra descriptive column or the same records in an unrequested display order.
It can also recognize that a truncated prefix is inadequate to decide a case.

It must not:

- Claim that matching previews prove matching complete results.
- Compare record positions when ordering is not part of the task.
- Independently match each column while losing record associations.
- Discard duplicates to hide a wrong join or grouping grain.
- Assume every difference is caused by sorting or ties.
- Invent an unshown record, ranking value, or key constraint.
- Treat a missing preview after execution failure as a successful empty result.

For two disjoint 50-row prefixes, "different ordering is possible" is weaker
than "the same complete answer is established." If the SQL and supplied facts
cannot resolve that difference, review is the appropriate status.

## Display order versus query semantics

There are two distinct limits:

- **Evaluator preview cap:** only a prefix is shown to control prompt size.
- **SQL selection limit:** LIMIT, TOP, FETCH, a rank filter, or similar SQL logic
  determines which records belong to the answer.

Sorting a preview after truncation cannot recover records omitted from it.
Without a unique ordering, the selected limited subset can vary. PostgreSQL's
[LIMIT documentation](https://www.postgresql.org/docs/current/queries-limit.html)
explains this behavior.

| Difference | How to assess it |
| --- | --- |
| Same required records, no requested display order | Allow different row order. |
| Same ranking values within a visible tie, no secondary key required | Allow different tie order. |
| Different truncated prefixes; equivalence and unseen ties are unknown | Request review. |
| DESC LIMIT 50 becomes ASC LIMIT 50 for a highest-sales question | Check as a population-selection error, not presentation. |
| Ordering changes a window frame or running total | Check computed-value semantics. |
| Question specifies all co-winners or a tie-break key | Enforce that stated requirement. |

## The semantic judge stays independent

The SQL-semantic call receives the question and both SQL queries, plus any
existing context or dialect. It receives no previews, counts or first-judge
decision. It directly compares the target and generated SQL for semantic
equivalence on the answer required by the question. The target supplies the
reference logic; the question determines whether a difference matters. The
judge must cite corresponding clauses from both queries, or identify a missing
clause. It does not require identical SQL text, structure, or supplementary
columns, and it must not pass a query just because it looks plausible alone.

For example, a target using `SUM(amount)` and a generated query using
`AVG(amount)` fail for a question asking for total sales. A target using a
subquery and a generated query using a CTE can pass when they preserve the same
required logic. If the target contradicts the question, request review and flag
the reference issue instead of rewarding the same mistake in generated SQL.

For example, a generated query may omit a required date filter yet match all
sampled rows because the current database contains only that date range. Sampled
consistency can pass, while semantic correctness should fail. Conversely, a
valid CTE rewrite or permitted information column should not fail merely because
the reference uses a subquery or fewer columns.

The judge must not invent business definitions or schema constraints. Reuse
context already available in your pipeline when possible. If an unknown
uniqueness or NULL constraint decides the case, request review.

[FLEX (NAACL 2025), section 5.2](https://aclanthology.org/2025.naacl-long.228.pdf)
studies SQL evaluation with question, schema and business context, and uses
different evidence for matching and non-matching execution results. It reports
that matching result evidence can distract a judge from logical defects. This
supports separating the two assessment roles, but does not validate this exact
two-judge, top-50 protocol or guarantee a particular error reduction.

## Interpret the rates

Use a fixed evaluation set of valid, answerable cases. Each rate is the number
of confirmed passes divided by that fixed case count. Report review cases and
operational errors separately. Do not silently exclude difficult cases or
average the three rates into one correctness score.

The team's classification convention is:

| Evaluator action | SQL actually wrong | SQL actually correct |
| --- | --- | --- |
| Flags SQL as wrong | True positive | False positive: false alarm |
| Accepts SQL | False negative: missed error | True negative |

The package's pass rates and this positive-class convention are different
concepts. A review is neither a confirmed error flag nor a confirmed acceptance.

## Calibrate before claiming improvement

Use a small human-reviewed set drawn from existing cases. Include harmless extra
columns, reordered rows, boundary ties, wrong values, wrong JOIN grain, missing
filters, NULL-dependent rewrites and ambiguous reference queries. Check both
false alarms and missed errors, with reviews reported separately.

Keep the model version, prompt version and input data conditions stable when
comparing runs. Two judge calls can share model errors; their agreement is
supporting evidence rather than independent proof. Matching all three metrics
does not establish semantic correctness on every possible database.
