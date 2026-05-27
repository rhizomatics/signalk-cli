"""CSV and Feather output writers for SignalK data."""

import csv
import json
import sys

import pyarrow as pa
import pyarrow.feather as feather


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
    """Write result as CSV rows to sink. Returns (row_count, unique_paths)."""
    timestamps, paths, values, unique_paths = extract_rows(result)
    writer = csv.writer(sink)
    if not no_header:
        writer.writerow(["timestamp", "path", "value"])
    for ts, path, val in zip(timestamps, paths, values):
        writer.writerow([ts, path, val])
    return len(timestamps), unique_paths


def write_feather(result: dict, output: str) -> tuple[int, set[str]]:
    """Write result as Apache Arrow Feather to output path. Returns (row_count, unique_paths)."""
    timestamps, paths, values, unique_paths = extract_rows(result)
    table = pa.table({
        "timestamp": pa.array(timestamps, type=pa.string()),
        "path":      pa.array(paths,      type=pa.string()),
        "value":     pa.array(values,     type=pa.string()),
    })
    feather.write_feather(table, output)
    return len(timestamps), unique_paths


def csv_sink(output: str, write_to_file: bool, write_to_stdout: bool):
    """Return (file_handle_or_None, sink) for CSV writing. Caller must close file_handle."""
    file_fh = open(output, "w", newline="") if write_to_file else None
    if write_to_file and write_to_stdout:
        sink = _MultiWriter(file_fh, sys.stdout)
    elif write_to_file:
        sink = file_fh
    else:
        sink = sys.stdout
    return file_fh, sink
