## Metric: SQL semantic pass

Your job is to assess whether the generated SQL satisfies the natural-language
question under the supplied context, using the target SQL as a reference.
Do not ask whether the SQL strings are identical, whether their syntax trees
match, or whether the complete projected outputs contain exactly the same
columns. Valid SQL can differ in text, structure and supplementary information.

The packet contains the question, target SQL, generated SQL, and optional
dialect/context. It intentionally contains no execution previews, row counts,
or other judge's decision. Do not infer or assume any of them. Judge SQL logic
independently of current database contents.

This is an evidence-based LLM assessment, not a proof that two arbitrary SQL
queries are equivalent on every possible database. Use unknown constraints and
ambiguous task requirements as reasons for review, not grounds for an invented
proof or an automatic failure.

## Evaluation procedure

1. Read the question before comparing queries. Extract the required answer:
   entities, measures, output grain, inclusion/exclusion criteria, dates, units,
   ordering, ranking, and limits. Use supplied context to resolve terminology.
   Do not invent a semantic model when none is supplied.

2. Compare each query's logic with those requirements. Use the reference to
   identify the intended operations, but check whether a difference affects the
   requested answer. Neither textual similarity nor difference determines the
   verdict. If the reference appears inconsistent with the question and the
   discrepancy prevents a trustworthy benchmark decision, request review and
   identify the reference issue.

3. Check the following requirements wherever they matter:
   - Tables, fields and roles: do the selected fields identify the requested
     entities and use the requested measure definition? Do not equate columns
     merely because names or presumed values are similar.
   - Filters: preserve requested predicates, boolean grouping, comparisons,
     inclusion/exclusion logic, HAVING versus WHERE behavior, and required
     correlated conditions. An omitted condition is a logical defect even if
     today's database might make it redundant.
   - Joins: check keys, inner versus outer behavior, filtering on nullable outer
     sides, cardinality and duplicate amplification. Do not assume a key is
     unique or a join is lossless without supplied evidence. A rewrite using
     EXISTS can be valid, but may differ from a join under bag semantics.
   - Aggregation and grain: preserve grouping entities, aggregate functions,
     weighting, numerator/denominator definitions, DISTINCT behavior and
     aggregation before or after joins. Adding a supplementary attribute must
     not split one requested group into multiple groups or inflate measures.
   - Dates and time: preserve requested range, inclusive/exclusive boundaries,
     date truncation, calendar versus rolling periods, timezone and fixed versus
     current dates. Do not invent the evaluation date or business timezone.
   - NULL and empty inputs: check COUNT(*) versus COUNT(column), nullable
     comparisons, NULL-sensitive predicates such as NOT IN, aggregate handling,
     COALESCE and possible empty groups. Do not assume nullable columns are
     non-null or that an empty sum equals zero without context.
   - Duplicates and set operations: preserve multiplicity when the task needs
     it; inspect DISTINCT, UNION versus UNION ALL, and deduplication choices.
     Do not require identical duplicate behavior when the task explicitly asks
     for a set of entities and both queries implement that set correctly.
   - Sorting, ranking and top-K: distinguish optional display order from
     ordering that determines selected records, ROW_NUMBER/RANK/DENSE_RANK,
     first/last values, cumulative calculations and window frames. Preserve
     the requested direction, partition, tie policy, threshold and limits.
   - Values and representations: preserve units, ratios, percentages, boolean
     meanings, precision and type operations where they affect the required
     answer. Harmless display transformations may be allowed; do not infer an
     unexplained unit conversion.
   - Dialect: use the supplied dialect when available. Do not reject an
     expression valid in that dialect merely because another dialect differs.
     If dialect uncertainty is decisive, request review.

4. Allow task-equivalent alternatives supported by ordinary SQL semantics or
   supplied facts: aliases, CTEs versus subqueries, different join order where
   equivalent, suitable aggregate rewrites, equivalent filter expressions,
   permitted information columns, and harmless final display ordering. Explain
   why a material-looking difference is harmless. Do not add imagined keys,
   non-null constraints, functional dependencies or domain conventions to make
   a rewrite work.

5. Judge potential logic errors independently of accidental current values.
   A query selecting the wrong dates, extra population, wrong aggregate or
   incorrect top-K does not become semantically correct because it might return
   matching data on a particular snapshot. Conversely, do not fail solely
   because two valid interpretations would happen to return different records.
   Resolve the question or request review.

6. Return a short decision with inspectable evidence. Cite the SQL clauses that
   preserve or violate a question requirement, or identify the precise missing
   context. Avoid vague reasons such as "the queries are different" or "both
   look equivalent." Do not provide private chain-of-thought.

## Decision rules

`PASS`, `needs_review: false`:
The available question, reference, SQL and context support that the generated
query implements the requested meaning. Differences are task-irrelevant or
supported equivalent formulations. This is a judge assessment, not a formal
proof or a claim about execution results.

`FAIL`, `needs_review: false`:
The generated query demonstrably violates a requested requirement under the
available information. Cite the requirement and the SQL clause or omission.
Do not require a visible counterexample row to reject a logical defect.

`needs_review: true`, provisional `verdict: PASS`:
A decisive missing schema fact, business definition, dialect detail, ambiguous
question or questionable reference prevents a reliable decision. State the
missing fact rather than guessing. The application records REVIEW with no
numeric score. Use this only for a material uncertainty, not every theoretical
possibility about a database.

## Worked examples

### Equivalent structure

Question: "Show total sales by customer."
Target groups the sales table by customer in a subquery. Generated uses a CTE
for the same grouping and selects the same measure under different aliases.
There are no other semantic differences. Return PASS without review; identify
the same grouping key and SUM expression.

### Extra information with supported grain

The generated query adds customer_name by joining an explicitly supplied
unique customer key after computing the requested per-customer totals. The
join is documented as complete and one-to-one. Return PASS without review.
If that uniqueness/completeness is decisive but not supplied and cannot be
established from the queries, request review rather than assuming it.

### Missing date restriction

Question: "What are sales in January 2025?"
Target restricts sale_date to January 2025. Generated sums all sales with no
equivalent date restriction. Return FAIL without review. The database might
currently contain only January rows, but that possibility does not repair the
missing requirement.

### Ordering that changes top-K

Question: "Return the ten highest-selling products."
Target uses a descending sales order with LIMIT 10; generated uses an ascending
order with the same limit. Return FAIL without review. The order chooses a
different population; it is not a cosmetic display change.

### Unspecified tie behavior

Question: "Who has the highest score?"
The reference uses descending ORDER BY with LIMIT 1; generated selects every
record equal to MAX(score). If no context establishes whether one winner or
all co-winners are required, request review. Do not infer unique scores and do
not reject all-co-winner behavior merely because the reference selects one.
If the question says "all tied winners," the generated form can pass and a
reference limited to one may need correction.

### A NULL-dependent rewrite

Target uses COUNT(order_id); generated uses COUNT(*). If order_id is explicitly
non-null on all counted rows, the rewrite can pass. If NULL can demonstrably
occur and the question requires counting non-null order IDs, fail. If nullable
status is unknown and decisive, request review; do not invent a constraint.
