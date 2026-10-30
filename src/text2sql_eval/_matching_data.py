"""Validate tabular inputs and preserve typed cell values for subset matching."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

import numpy as np

from text2sql_eval.models import QueryResult

Cell = tuple[str, Any]
Signature = frozenset[tuple[Cell, int]]


def _is_pandas_type(value: Any) -> bool:
    return any(base.__module__.partition(".")[0] == "pandas" for base in type(value).__mro__)


def canonical_cell(value: Any, *, _active: frozenset[int] = frozenset()) -> Cell:
    """Use logical types; never coerce Boolean/string values to numbers."""
    if value is None:
        return ("null", None)
    # Pandas is optional. Its sentinels can occur only if pandas is already installed.
    if _is_pandas_type(value):
        import pandas as pd

        if value is pd.NA or value is pd.NaT:
            return ("null", None)
    if isinstance(value, np.datetime64):
        if np.isnat(value):
            return ("null", None)
        raise TypeError("Convert numpy.datetime64 cells to datetime or pandas.Timestamp.")
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, bool):
        return ("boolean", value)
    if isinstance(value, int):
        return ("number", Decimal(value))
    if isinstance(value, (float, Decimal)):
        if isinstance(value, float):
            if math.isnan(value):
                return ("null", None)
            if not math.isfinite(value):
                raise ValueError("Infinite numeric cells are not supported.")
            return ("number", Decimal(str(value)))
        if value.is_nan():
            return ("null", None)
        if not value.is_finite():
            raise ValueError("Infinite numeric cells are not supported.")
        return ("number", value)
    if isinstance(value, str):
        return ("string", value)
    if isinstance(value, bytes):
        return ("bytes", value)
    if isinstance(value, datetime):
        return ("datetime", value.isoformat())
    if isinstance(value, date):
        return ("date", value.isoformat())
    if isinstance(value, time):
        return ("time", value.isoformat())
    if isinstance(value, (list, tuple, Mapping)):
        if id(value) in _active:
            raise ValueError("Cyclic cell values are not supported.")
        if len(_active) >= 100:
            raise ValueError("Nested cell values may have at most 100 container levels.")
        active = _active | {id(value)}
        if isinstance(value, Mapping):
            if any(not isinstance(key, str) for key in value):
                raise TypeError("Object cell keys must be strings.")
            return (
                "object",
                tuple((key, canonical_cell(value[key], _active=active)) for key in sorted(value)),
            )
        return ("array", tuple(canonical_cell(item, _active=active) for item in value))
    raise TypeError(f"Unsupported cell type: {type(value).__name__}.")


def row_signature(row: Iterable[Any]) -> Signature:
    """Ignore field ordering and labels while retaining repeated cell values."""
    if isinstance(row, (str, bytes, Mapping)):
        raise TypeError("A row must be a sequence of cell values, not a string or mapping.")
    try:
        return frozenset(Counter(canonical_cell(value) for value in row).items())
    except TypeError as exc:
        raise TypeError(f"Invalid row: {exc}") from exc


def dataset_rows(data: Any) -> tuple[list[Signature], int]:
    """Read complete rectangular rows; DataFrame labels and index are ignored."""
    width: int | None = None
    if isinstance(data, QueryResult):
        data = {
            "columns": data.columns,
            "rows": data.rows,
            "total_rows": data.total_rows,
            "execution_error": data.execution_error,
        }
    if isinstance(data, Mapping):
        allowed = {"columns", "rows", "total_rows", "execution_error"}
        if set(data) - allowed or "rows" not in data or "columns" not in data:
            raise ValueError("A dataset object needs columns and rows, with optional total_rows.")
        if data.get("execution_error") is not None:
            raise ValueError("Failed query results cannot be compared.")
        columns = data["columns"]
        if not isinstance(columns, (list, tuple)):
            raise TypeError("Dataset columns must be a list or tuple.")
        width = len(columns)
        rows = data["rows"]
        if not isinstance(rows, (list, tuple)):
            raise TypeError("Dataset rows must be a list or tuple.")
        if "total_rows" in data:
            total = data["total_rows"]
            if type(total) is not int or total < 0 or total != len(rows):
                raise ValueError(
                    "Comparison requires complete rows: total_rows must equal len(rows)."
                )
    elif _is_pandas_type(data):
        import pandas as pd

        if not isinstance(data, pd.DataFrame):
            raise TypeError("Use a pandas DataFrame, not a Series or Index.")
        width = len(data.columns)
        rows = data.itertuples(index=False, name=None) if width else (() for _ in range(len(data)))
    else:
        if isinstance(data, (str, bytes)) or not isinstance(data, Iterable):
            raise TypeError(
                "Use a DataFrame, an iterable of rows, or a columns/rows dataset object."
            )
        rows = data

    signatures: list[Signature] = []
    record_keys: frozenset[Any] | None = None
    row_kind: str | None = None
    for index, row in enumerate(rows):
        if isinstance(row, Mapping):
            if width is not None and row_kind is None:
                raise TypeError(
                    "columns/rows datasets require positional rows, not record objects."
                )
            if row_kind == "positional":
                raise TypeError("Do not mix positional rows and record objects.")
            keys = frozenset(row)
            if record_keys is not None and record_keys != keys:
                raise ValueError("All record objects must have the same field names.")
            record_keys = keys
            row_kind = "record"
            values = tuple(row.values())
        else:
            if row_kind == "record":
                raise TypeError("Do not mix record objects and positional rows.")
            row_kind = "positional"
            if isinstance(row, (str, bytes)) or not isinstance(row, (Sequence, np.ndarray)):
                raise TypeError(f"Row {index} must be a sequence of cell values.")
            values = tuple(row)
        if width is None:
            width = len(values)
        elif len(values) != width:
            raise ValueError(f"Row {index} has {len(values)} cells; expected {width}.")
        try:
            signatures.append(row_signature(values))
        except (TypeError, ValueError) as exc:
            raise type(exc)(f"Row {index}: {exc}") from exc
    return signatures, width or 0
