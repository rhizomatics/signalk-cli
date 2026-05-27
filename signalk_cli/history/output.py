"""CSV and Feather output writers for SignalK data."""

import csv
import json
import sys
from typing import IO, cast

import pyarrow as pa
import pyarrow.feather as feather

FEATHER_EXTENSIONS = {".feather", ".arrow", ".fea"}


class _MultiWriter:
    """Fans writes out to multiple underlying streams."""

    def __init__(self, *fhs):
        self._fhs = fhs

    def write(self, s):
        for fh in self._fhs:
            fh.write(s)

    def flush(self):
        for fh in self._fhs:
            fh.flush()


# ---------------------------------------------------------------------------
# Narrow mode (single value column)
# ---------------------------------------------------------------------------


def extract_rows(result: dict) -> tuple[list, list, list, set[str]]:
    """Flatten an API result into parallel (timestamps, paths, values, unique_paths) lists."""
    value_columns = result.get("values", [])
    data_rows = result.get("data", [])
    timestamps, paths, values = [], [], []
    unique_paths: set[str] = set()

    for row in data_rows:
        if not row:
            continue
        timestamp = row[0]
        for i, col in enumerate(value_columns):
            path_name = col.get("path", f"col_{i}")
            value = row[i + 1] if i + 1 < len(row) else None
            if value is None:
                continue
            if isinstance(value, (dict, list)):
                value = json.dumps(value)
            elif not isinstance(value, str):
                value = str(value)
            timestamps.append(timestamp)
            paths.append(path_name)
            values.append(value)
            unique_paths.add(path_name)

    return timestamps, paths, values, unique_paths


def write_csv(result: dict, sink, no_header: bool) -> tuple[int, set[str]]:
    """Write result as CSV rows (timestamp, path, value). Returns (row_count, unique_paths)."""
    timestamps, paths, values, unique_paths = extract_rows(result)
    writer = csv.writer(sink)
    if not no_header:
        writer.writerow(["timestamp", "path", "value"])
    for ts, path, val in zip(timestamps, paths, values):
        writer.writerow([ts, path, val])
    return len(timestamps), unique_paths


def write_feather(result: dict, output: str) -> tuple[int, set[str]]:
    """Write result as Feather (timestamp, path, value). Returns (row_count, unique_paths)."""
    timestamps, paths, values, unique_paths = extract_rows(result)
    table = pa.table(
        {
            "timestamp": pa.array(timestamps, type=pa.string()),
            "path": pa.array(paths, type=pa.string()),
            "value": pa.array(values, type=pa.string()),
        }
    )
    feather.write_feather(table, output)
    return len(timestamps), unique_paths


# ---------------------------------------------------------------------------
# Wide mode (min_value / max_value / avg_value columns)
# ---------------------------------------------------------------------------


def _cell(row: list, col_idx: int) -> str:
    """Get a string cell value from a data row by 0-based column index (row[0] is timestamp)."""
    i = col_idx + 1
    if i >= len(row):
        return ""
    v = row[i]
    if v is None:
        return ""
    if isinstance(v, (dict, list)):
        return json.dumps(v)
    return str(v)


def extract_rows_wide(result: dict) -> tuple[list, list, list, list, list, set[str]]:
    """Extract rows as (timestamps, paths, min_vals, max_vals, avg_vals, unique_paths)."""
    value_columns = result.get("values", [])
    data_rows = result.get("data", [])

    # Build {path: {method: col_idx}} preserving path order
    path_method_idx: dict[str, dict[str, int]] = {}
    for i, col in enumerate(value_columns):
        path = col.get("path", f"col_{i}")
        method = col.get("method", "")
        path_method_idx.setdefault(path, {})[method] = i

    ordered_paths = list(path_method_idx)
    timestamps, paths_out, min_vals, max_vals, avg_vals = [], [], [], [], []
    unique_paths: set[str] = set()

    for row in data_rows:
        if not row:
            continue
        ts = row[0]
        for path in ordered_paths:
            methods = path_method_idx[path]
            mn = _cell(row, methods["min"]) if "min" in methods else ""
            av = _cell(row, methods["average"]) if "average" in methods else ""
            mx = _cell(row, methods["max"]) if "max" in methods else ""
            if not mn and not av and not mx:
                continue
            timestamps.append(ts)
            paths_out.append(path)
            min_vals.append(mn)
            avg_vals.append(av)
            max_vals.append(mx)
            unique_paths.add(path)

    return timestamps, paths_out, min_vals, max_vals, avg_vals, unique_paths


def write_csv_wide(result: dict, sink, no_header: bool) -> tuple[int, set[str]]:
    """Write result as CSV (timestamp, path, min_value, max_value, avg_value)."""
    timestamps, paths, min_vals, max_vals, avg_vals, unique_paths = extract_rows_wide(
        result
    )
    writer = csv.writer(sink)
    if not no_header:
        writer.writerow(["timestamp", "path", "min_value", "avg_value", "max_value"])
    for row in zip(timestamps, paths, min_vals, avg_vals, max_vals):
        writer.writerow(row)
    return len(timestamps), unique_paths


def write_feather_wide(result: dict, output: str) -> tuple[int, set[str]]:
    """Write result as Feather (timestamp, path, min_value, max_value, avg_value)."""
    timestamps, paths, min_vals, max_vals, avg_vals, unique_paths = extract_rows_wide(
        result
    )
    table = pa.table(
        {
            "timestamp": pa.array(timestamps, type=pa.string()),
            "path": pa.array(paths, type=pa.string()),
            "min_value": pa.array(min_vals, type=pa.string()),
            "avg_value": pa.array(avg_vals, type=pa.string()),
            "max_value": pa.array(max_vals, type=pa.string()),
        }
    )
    feather.write_feather(table, output)
    return len(timestamps), unique_paths


# ---------------------------------------------------------------------------
# Sink helper
# ---------------------------------------------------------------------------


def csv_sink(
    output: str, write_to_file: bool, write_to_stdout: bool
) -> tuple[IO[str] | None, _MultiWriter | IO[str]]:
    """Return (file_handle_or_None, sink) for CSV writing. Caller must close file_handle."""
    file_fh: IO[str] | None = open(output, "w", newline="") if write_to_file else None
    sink: _MultiWriter | IO[str]
    if write_to_file and write_to_stdout:
        sink = _MultiWriter(cast(IO[str], file_fh), sys.stdout)
    elif write_to_file:
        sink = cast(IO[str], file_fh)
    else:
        sink = sys.stdout
    return file_fh, sink
