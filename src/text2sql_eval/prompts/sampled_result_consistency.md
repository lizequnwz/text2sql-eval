## Metric: sampled result consistency

Your job is to compare the supplied execution evidence for the target and
generated SQL, using the question and both queries to interpret that evidence.
This metric measures whether the available evidence contains a material
contradiction in the required answer. It does not measure full-result equality
and does not prove SQL correctness.

The packet contains the question, target SQL, generated SQL, optional dialect
and context, and execution information for each query. Each preview associates
an ordered list of column names with row-value lists. Read the preview metadata:
complete result row count, supplied row count, displayed row count, whether
truncated, and any execution error. Only the displayed records are visible to
you. The application displays at most the first 50 rows of each supplied result.

A display cap imposed by the evaluator is different from a `LIMIT`, `TOP`,
`FETCH`, qualifying rank, or equivalent operation inside the SQL. An absent
record in one preview can be outside its displayed prefix. Never claim to have
compared unshown rows. If execution failed, do not treat its missing preview as
a successfully executed empty result.

## Evaluation procedure

1. Identify the answer requirements from the question: required entities,
   measures, grouping grain, time scope, ordering, and any top-K or tie rule.
   Use the target SQL and available context to interpret those requirements.
   If interpretation depends on unavailable business information, mark review.

2. Establish a consistent mapping of the required target and generated fields.
   Aliases and supplementary columns are permitted when they preserve the
   required information. Match an identifier to the same entity and a measure
   to the same definition and unit. Do not select whichever numeric column
   happens to match separately for each row. If no defensible mapping can be
   established, distinguish a clearly missing required field from ambiguity.

3. Compare records at the required grain. Where identifiers and grouping keys
   are available, use them to align records across previews. Compare required
   values on aligned records. Do not compare by display position, independently
   compare each column as a set, or discard required record associations.
   Inspect visible duplicates in light of the SQL and task. Do not silently
   deduplicate a one-to-many expansion that violates the requested grain.

4. Assess differences in ordering and displayed membership:
   - If the task does not require a final display order, different final row
     order is acceptable. The same full result may have different prefixes.
   - If order is required, check the requested keys and directions. Do not
     require an unrequested secondary order within a legitimate tie group.
   - Without a unique ordering, an evaluator's first-50-row preview can include
     different records. This is a possible explanation, not proof that any two
     samples come from the same complete answer.
   - A tie crossing the preview boundary can hide an otherwise valid record.
     Recognize this limit, but do not assert that unshown records exist or are
     tied merely because the prefixes differ.
   - Do not ignore order used to select top/bottom K, choose a first/last row,
     assign ranks, compute a window or running total, or define a frame. For a
     "highest sales" task, `ORDER BY sales DESC LIMIT 50` and `ORDER BY sales
     ASC LIMIT 50` choose different populations. They are not equivalent
     display choices.
   - A stated tie-break key or "include all ties" requirement is part of the
     task. Do not replace it with an arbitrary selection policy.

5. Use the SQL to explain observed execution differences only when that
   explanation is supported. A proven task-equivalent rewrite, harmless field
   addition, or clearly supported permitted reordering may justify the preview
   difference. A suspected tie, unknown uniqueness constraint, or vague claim
   that the queries "look similar" does not. A disjoint pair of truncated
   samples usually needs review when equivalence cannot be established from
   the available SQL and context.

6. Use total row counts as an additional observation, not an automatic final
   correctness decision. Equal counts do not prove equal values. Different
   counts can demonstrate a problem when the task requires the same grain and
   complete membership; they can also reflect an allowed multiple-answer or
   tie interpretation. When the interpretation is unresolved, request review.
   Two empty results contain no positive evidence about answer values. If they
   are valid successful executions with no demonstrated contradiction, a
   sampled-consistency pass can be appropriate, but explicitly state that the
   empty evidence does not establish semantic correctness.

7. Give a supported decision. Focus on the supplied execution evidence. Leave
   a purely logical defect with no demonstrated result contradiction to the
   independent SQL-semantic metric; do not pretend an unseen data difference
   was observed. You may cite SQL as support for a definite interpretation of
   visible records, their units, grain, ordering, or membership.

## Decision rules

`PASS`, `needs_review: false`:
The supplied previews and relevant metadata contain no material contradiction
in the required answer after supported field mapping and permitted presentation
differences. Describe the scope accurately: sampled evidence is consistent, not
"all rows match" or "the SQL is correct." A known count difference or visible
value difference must be explained under the task before an automatic pass.

`FAIL`, `needs_review: false`:
The packet demonstrates an incompatible required fact, missing required output,
wrong visible association, invalid multiplicity/grain, or a required ordering
or membership violation. Cite the concrete evidence. Do not base failure solely
on different row positions, permitted extra columns, or an unresolved boundary.

`needs_review: true`, provisional `verdict: PASS`:
The preview, mapping, context, or SQL does not resolve whether an apparent
difference is allowed. State precisely what is unknown. For example, the two
50-row prefixes contain different customer IDs and no complete membership or
supported equivalence evidence is available. The application records `REVIEW`,
not an automatic pass or failure.

## Worked examples

### Extra columns and harmless ordering

Question: "Show each customer's total sales."
Target fields: `customer_id, total_sales`.
Generated fields: `customer_id, customer_name, total_sales`.
Both complete results contain `(1, 100)` and `(2, 200)` for the required fields;
the displayed record order differs and the question does not request an order.
Return PASS without review. Explain the fixed required-field mapping and the
matching customer/amount pairs. Do not reject the supplementary name column.

### Different amount for the same record

The same task, same measure definition, same period and `customer_id=1` are
visible in both previews. Target has `total_sales=100`, generated has
`total_sales=900`, with no supported unit or representation explanation.
Return FAIL without review. A different ORDER BY cannot change the amount for
the same aligned customer; it only changes display or selected membership.

### Different truncated prefixes without adequate explanation

Each complete result has 1,000 rows. The previews show 50 different customer IDs
with no overlap. The queries differ in joins or filters whose equivalence
depends on unavailable constraints. There is no unique final ordering.
Return needs_review true. Do not fail because the displayed IDs differ, and do
not pass automatically because arbitrary preview order is possible. No ordering
guarantee explains neither the join/filter equivalence nor full membership.

### A permitted tie

Question: "Show customers by total sales, highest first."
Both successful results show the same customers and sales values. Customers
with sales 100 appear in opposite order; all requested ordering keys agree.
Return PASS without review. Cite the equal ranking values and absence of a
required secondary key. If a record appears beyond the displayed boundary and
its value is not supplied, do not invent its tie value.

### A selected population changes

Question: "Return the 50 customers with the highest total sales."
Target uses `ORDER BY total_sales DESC LIMIT 50`; generated uses `ASC LIMIT 50`.
The supplied results show different customers with lower generated sales, and
the evidence excludes an all-equal tie explanation.
Return FAIL without review. Cite the direction/limit difference and the observed
membership/measure evidence. This is not harmless display randomization.

### Preview agreement with a latent logical defect

Question: "Show this month's sales by customer."
Generated SQL omits the month filter, but the supplied matching previews and
counts contain no demonstrated wrong-period contribution. The execution
evidence can pass sampled consistency; say only that no contradiction was
observed in the sample. Do not claim semantic correctness. The separate SQL
judge must assess the omitted filter without being anchored by these rows.
