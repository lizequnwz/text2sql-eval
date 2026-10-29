"""The shared evidence window used by the sampled judge and HTML reader."""

from text2sql_eval.models import QueryResult

PREVIEW_LIMIT = 50


def preview_result(result: QueryResult) -> dict[str, object]:
    """Cap the actual payload, not merely the visible HTML, at fifty rows."""
    shown_rows = min(len(result.rows), PREVIEW_LIMIT)
    return {
        "columns": result.columns,
        "rows": result.rows[:PREVIEW_LIMIT],
        "total_rows": result.total_rows,
        "provided_rows": len(result.rows),
        "shown_rows": shown_rows,
        "truncated": result.total_rows is not None and result.total_rows > shown_rows,
        "execution_error": result.execution_error,
    }
