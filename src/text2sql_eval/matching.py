"""Deterministic value-multiset containment within rows and across row occurrences.

No column names, essential-field annotations, SQL execution, or LLM calls are used.
"""

from __future__ import annotations

from collections import Counter, defaultdict, deque
from typing import Any, Literal

import numpy as np
from pydantic import Field
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import maximum_flow

from text2sql_eval._matching_data import Signature, dataset_rows, row_signature
from text2sql_eval.models import StrictModel

SubsetPolicy = Literal["equal", "target_subset", "generated_subset", "bidirectional"]
RowRelation = Literal["equal", "target_subset", "generated_subset", "incompatible"]
DatasetRelation = Literal[
    "full_match", "target_subset", "generated_subset", "partial_overlap", "no_match"
]


class MatchingConfig(StrictModel):
    """Control permitted row and dataset containment directions independently."""

    row_policy: SubsetPolicy = "bidirectional"
    dataset_policy: SubsetPolicy = "bidirectional"
    max_candidate_edges: int = Field(default=1_000_000, ge=1)


class RowComparison(StrictModel):
    """Observed value relationship plus the configured acceptance decision."""

    accepted: bool
    relation: RowRelation
    target_value_count: int
    generated_value_count: int


class RowMatch(StrictModel):
    """Distinct zero-based positional occurrences; DataFrame index labels are ignored."""

    target_index: int
    generated_index: int
    relation: RowRelation


class DatasetComparison(StrictModel):
    """Dataset relationship under row_policy, not a claim of SQL correctness."""

    accepted: bool
    relation: DatasetRelation
    reason: str
    config: MatchingConfig
    target_row_count: int
    generated_row_count: int
    matched_row_count: int
    row_count_match: bool
    target_coverage: float | None
    generated_coverage: float | None
    f1: float
    row_relation_counts: dict[str, int]
    matches: list[RowMatch]
    unmatched_target_indices: list[int]
    unmatched_generated_indices: list[int]


def _row_relation(target: Signature, generated: Signature) -> RowRelation:
    if target == generated:
        return "equal"
    target_counts, generated_counts = dict(target), dict(generated)
    if all(count <= generated_counts.get(value, 0) for value, count in target_counts.items()):
        return "target_subset"
    if all(count <= target_counts.get(value, 0) for value, count in generated_counts.items()):
        return "generated_subset"
    return "incompatible"


def _row_allowed(relation: RowRelation, policy: SubsetPolicy) -> bool:
    return relation == "equal" or (
        relation != "incompatible" and (policy == "bidirectional" or policy == relation)
    )


def compare_rows(
    target: Any, generated: Any, *, policy: SubsetPolicy = "bidirectional"
) -> RowComparison:
    """Compare row value multisets, ignoring column order and preserving cell counts."""
    config = MatchingConfig(row_policy=policy)
    target_signature, generated_signature = row_signature(target), row_signature(generated)
    relation = _row_relation(target_signature, generated_signature)
    return RowComparison(
        accepted=_row_allowed(relation, config.row_policy),
        relation=relation,
        target_value_count=sum(count for _, count in target_signature),
        generated_value_count=sum(count for _, count in generated_signature),
    )


def _groups(rows: list[Signature]) -> dict[Signature, deque[int]]:
    grouped: dict[Signature, deque[int]] = defaultdict(deque)
    for index, signature in enumerate(rows):
        grouped[signature].append(index)
    return dict(grouped)


def _candidate_edges(
    target: list[Signature],
    generated: list[Signature],
    *,
    target_is_narrower: bool,
    limit: int,
) -> list[tuple[int, int]]:
    """Index cell values to avoid an all-pairs scan for selective narrow rows."""
    narrow, wide = (target, generated) if target_is_narrower else (generated, target)
    postings: dict[Any, set[int]] = defaultdict(set)
    wide_counts = [dict(signature) for signature in wide]
    for index, counts in enumerate(wide_counts):
        for token in counts:
            postings[token].add(index)
    edges: list[tuple[int, int]] = []
    for narrow_index, signature in enumerate(narrow):
        counts = dict(signature)
        if counts and any(token not in postings for token in counts):
            continue
        if counts:
            # Sorting is only for reproducible traversal, never for record alignment.
            rarest = min(counts, key=lambda token: len(postings[token]))
            candidates = sorted(postings[rarest])
        else:
            candidates = range(len(wide))
        for wide_index in candidates:
            if all(
                count <= wide_counts[wide_index].get(token, 0) for token, count in counts.items()
            ):
                if len(edges) >= limit:
                    raise ValueError(
                        f"Comparison exceeds max_candidate_edges={limit}; the unique-row "
                        "containment graph is too dense. No comparison decision was produced. "
                        "Increase the limit only if sufficient memory is available."
                    )
                edges.append(
                    (narrow_index, wide_index) if target_is_narrower else (wide_index, narrow_index)
                )
    return edges


def _matching_pairs(
    target_rows: list[Signature],
    generated_rows: list[Signature],
    target_width: int,
    generated_width: int,
    config: MatchingConfig,
) -> list[RowMatch]:
    if not target_rows or not generated_rows:
        return []
    target_groups, generated_groups = _groups(target_rows), _groups(generated_rows)
    if target_width == generated_width:
        # Equal-size multiset containment is equality, regardless of subset policy.
        matches: list[RowMatch] = []
        for signature, target_indices in target_groups.items():
            generated_indices = generated_groups.get(signature, deque())
            for _ in range(min(len(target_indices), len(generated_indices))):
                matches.append(
                    RowMatch(
                        target_index=target_indices.popleft(),
                        generated_index=generated_indices.popleft(),
                        relation="equal",
                    )
                )
        return sorted(matches, key=lambda match: match.target_index)

    relation: RowRelation = (
        "target_subset" if target_width < generated_width else "generated_subset"
    )
    if not _row_allowed(relation, config.row_policy):
        return []
    target_signatures, generated_signatures = list(target_groups), list(generated_groups)
    edges = _candidate_edges(
        target_signatures,
        generated_signatures,
        target_is_narrower=target_width < generated_width,
        limit=config.max_candidate_edges,
    )
    if not edges:
        return []

    # Capacities preserve occurrence counts without expanding duplicate pairs.
    target_occurrences, generated_occurrences = (
        list(target_groups.values()),
        list(generated_groups.values()),
    )
    target_count, generated_count = len(target_occurrences), len(generated_occurrences)
    generated_start, sink = 1 + target_count, 1 + target_count + generated_count
    row_indices: list[int] = []
    col_indices: list[int] = []
    capacities: list[int] = []
    for index, occurrences in enumerate(target_occurrences):
        row_indices.append(0)
        col_indices.append(index + 1)
        capacities.append(len(occurrences))
    for index, occurrences in enumerate(generated_occurrences):
        row_indices.append(generated_start + index)
        col_indices.append(sink)
        capacities.append(len(occurrences))
    for target_index, generated_index in edges:
        row_indices.append(target_index + 1)
        col_indices.append(generated_start + generated_index)
        capacities.append(
            min(len(target_occurrences[target_index]), len(generated_occurrences[generated_index]))
        )
    graph = csr_matrix(
        (np.asarray(capacities, dtype=np.int64), (row_indices, col_indices)),
        shape=(sink + 1, sink + 1),
        dtype=np.int64,
    )
    flow = maximum_flow(graph, 0, sink, method="dinic").flow.tocsr()
    flow.sort_indices()
    matches = []
    for index, target_indices in enumerate(target_occurrences):
        for offset in range(flow.indptr[index + 1], flow.indptr[index + 2]):
            generated_index = int(flow.indices[offset]) - generated_start
            amount = int(flow.data[offset])
            if amount <= 0 or not 0 <= generated_index < generated_count:
                continue
            generated_indices = generated_occurrences[generated_index]
            for _ in range(amount):
                matches.append(
                    RowMatch(
                        target_index=target_indices.popleft(),
                        generated_index=generated_indices.popleft(),
                        relation=relation,
                    )
                )
    return sorted(matches, key=lambda match: match.target_index)


def compare_datasets(
    target: Any, generated: Any, *, config: MatchingConfig | None = None
) -> DatasetComparison:
    """Find maximum one-to-one containment matching over complete tabular outputs.

    Accepts pandas DataFrames, rectangular row iterables, record-object iterables,
    or complete QueryResult/columns-and-rows objects. Labels and row/column order
    are ignored. Directions are always named relative to target and generated.
    """
    if config is None:
        config = MatchingConfig()
    config = MatchingConfig.model_validate(config)
    target_rows, target_width = dataset_rows(target)
    generated_rows, generated_width = dataset_rows(generated)
    target_count, generated_count = len(target_rows), len(generated_rows)
    if max(target_count, generated_count) > np.iinfo(np.int32).max:
        raise ValueError("Dataset occurrence counts exceed the maximum-flow capacity range.")
    matches = _matching_pairs(target_rows, generated_rows, target_width, generated_width, config)
    matched = len(matches)
    target_covered, generated_covered = matched == target_count, matched == generated_count
    relation: DatasetRelation
    if target_covered and generated_covered:
        relation = "full_match"
    elif target_covered:
        relation = "target_subset"
    elif generated_covered:
        relation = "generated_subset"
    elif matched:
        relation = "partial_overlap"
    else:
        relation = "no_match"
    accepted = {
        "equal": target_covered and generated_covered,
        "target_subset": target_covered,
        "generated_subset": generated_covered,
        "bidirectional": target_covered or generated_covered,
    }[config.dataset_policy]
    matched_target = {match.target_index for match in matches}
    matched_generated = {match.generated_index for match in matches}
    counts = {"equal": 0, "target_subset": 0, "generated_subset": 0}
    counts.update(Counter(match.relation for match in matches))
    return DatasetComparison(
        accepted=accepted,
        relation=relation,
        reason=(
            f"{'Accepted' if accepted else 'Rejected'} under row_policy={config.row_policy} "
            f"and dataset_policy={config.dataset_policy}: matched {matched} distinct row "
            f"occurrences out of target={target_count}, generated={generated_count}. "
            "This compares row value multisets; field meanings and SQL logic are not assessed."
        ),
        config=config,
        target_row_count=target_count,
        generated_row_count=generated_count,
        matched_row_count=matched,
        row_count_match=target_count == generated_count,
        target_coverage=matched / target_count if target_count else None,
        generated_coverage=matched / generated_count if generated_count else None,
        f1=2 * matched / (target_count + generated_count)
        if target_count + generated_count
        else 1.0,
        row_relation_counts=counts,
        matches=matches,
        unmatched_target_indices=[
            index for index in range(target_count) if index not in matched_target
        ],
        unmatched_generated_indices=[
            index for index in range(generated_count) if index not in matched_generated
        ],
    )
