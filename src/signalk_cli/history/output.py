"""CSV, JSON and Feather writers for the history CLI."""

import csv
import json
from typing import IO, Any

from .._arrow import ArrowTable, _as_text
from ._results import CARDINALITY_COLUMNS, long_rows, wide_rows

FEATHER_EXTENSIONS = {".feather", ".arrow", ".fea"}


def _text(v: Any) -> str:
    """CLI text for a value: JSON for objects/arrays, empty for null."""
    return _as_text(v) or ""


# ---------------------------------------------------------------------------
# Long (timestamp, path, value)
# ---------------------------------------------------------------------------


def write_csv(result: dict, sink: IO[str], no_header: bool) -> tuple[int, set[str]]:
    """Write result as CSV rows (timestamp, path, value). Returns (row_count, unique_paths)."""
    timestamps, paths, values = long_rows(result)
    writer = csv.writer(sink)
    if not no_header:
        writer.writerow(["timestamp", "path", "value"])
    for ts, path, val in zip(timestamps, paths, values):
        writer.writerow([ts, path, _text(val)])
    return len(timestamps), set(paths)


def write_json(
    result: dict, sink: IO[str], indent: int | None = None
) -> tuple[int, set[str]]:
    """Write result as a JSON array of {timestamp, path, value} objects."""
    timestamps, paths, values = long_rows(result)
    rows = [
        {"timestamp": ts, "path": p, "value": _text(v)}
        for ts, p, v in zip(timestamps, paths, values)
    ]
    sink.write(json.dumps(rows, indent=indent))
    return len(rows), set(paths)


# ---------------------------------------------------------------------------
# Wide (timestamp, path, min_value/avg_value/max_value or array element columns)
# ---------------------------------------------------------------------------


def write_csv_wide(
    result: dict, sink: IO[str], no_header: bool
) -> tuple[int, set[str]]:
    """Write result as CSV with wide value columns."""
    timestamps, paths, value_cols = wide_rows(result)
    col_names = list(value_cols)
    writer = csv.writer(sink)
    if not no_header:
        writer.writerow(["timestamp", "path", *col_names])
    for i, (ts, path) in enumerate(zip(timestamps, paths)):
        writer.writerow([ts, path, *(_text(value_cols[c][i]) for c in col_names)])
    return len(timestamps), set(paths)


def write_json_wide(
    result: dict, sink: IO[str], indent: int | None = None
) -> tuple[int, set[str]]:
    """Write result as a JSON array of wide row objects."""
    timestamps, paths, value_cols = wide_rows(result)
    rows = [
        {"timestamp": ts, "path": p, **{c: _text(v[i]) for c, v in value_cols.items()}}
        for i, (ts, p) in enumerate(zip(timestamps, paths))
    ]
    sink.write(json.dumps(rows, indent=indent))
    return len(rows), set(paths)


# ---------------------------------------------------------------------------
# Feather
# ---------------------------------------------------------------------------


def write_feather(table: ArrowTable, output: str) -> None:
    """Write a table to a Feather (Arrow IPC file) — needs pyarrow."""
    try:
        import pyarrow as pa
        from pyarrow import feather
    except ImportError:
        raise ImportError(
            "pyarrow is required for Feather output: pip install 'signalk-cli[feather]'"
        ) from None
    feather.write_feather(pa.table(table), output)


# ---------------------------------------------------------------------------
# Cardinality
# ---------------------------------------------------------------------------


def cardinality_text(row: dict[str, Any]) -> dict[str, str]:
    """Cardinality row as CLI text, with empty strings for stats that don't apply."""
    return {col: _text(row[col]) for col in CARDINALITY_COLUMNS}
