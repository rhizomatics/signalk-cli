"""CSV and Feather output writers for SignalK data."""

import csv
import json
import re
import sys
from typing import IO, cast

_POSITION_RE = re.compile(r"navigation.*\.position")

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
    try:
        import pyarrow as pa
        import pyarrow.feather as feather
    except ImportError:
        raise ImportError(
            "pyarrow is required for Feather output: pip install 'signalk-cli[feather]'"
        ) from None
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


def _peek_first_value(data_rows: list, col_idx: int):
    """First non-None value at col_idx+1 across data rows."""
    for row in data_rows:
        if row:
            i = col_idx + 1
            if i < len(row) and row[i] is not None:
                return row[i]
    return None


def _array_col_names(path: str, length: int) -> list[str]:
    """Column names for an array-valued path."""
    if length == 2 and _POSITION_RE.fullmatch(path):
        return ["longitude", "latitude"]
    return [f"value_{i}" for i in range(length)]


def extract_rows_wide(result: dict) -> tuple[list, list, dict[str, list], set[str]]:
    """Extract rows as (timestamps, paths, value_cols, unique_paths).

    value_cols is an ordered dict of column_name -> list of string values.
    Scalar paths produce min_value / avg_value / max_value columns.
    Array paths produce value_0 / value_1 / ... (or latitude / longitude for
    navigation.*.position paths of length 2).  Both may appear in one result;
    non-applicable cells are empty strings.
    """
    value_columns = result.get("values", [])
    data_rows = result.get("data", [])

    # Build {path: {method: col_idx}} preserving path order
    path_method_idx: dict[str, dict[str, int]] = {}
    for i, col in enumerate(value_columns):
        path = col.get("path", f"col_{i}")
        method = col.get("method", "")
        path_method_idx.setdefault(path, {})[method] = i

    ordered_paths = list(path_method_idx)

    # Determine per-path output columns by peeking at the first non-null value
    path_col_names: dict[str, list[str]] = {}
    path_is_array: dict[str, bool] = {}
    for path, methods in path_method_idx.items():
        sample = None
        for col_idx in methods.values():
            sample = _peek_first_value(data_rows, col_idx)
            if sample is not None:
                break
        if isinstance(sample, list):
            path_is_array[path] = True
            path_col_names[path] = _array_col_names(path, len(sample))
        else:
            path_is_array[path] = False
            path_col_names[path] = ["min_value", "avg_value", "max_value"]

    # Collect all unique column names in first-seen order
    all_col_names: list[str] = []
    seen_cols: set[str] = set()
    for path in ordered_paths:
        for col in path_col_names[path]:
            if col not in seen_cols:
                all_col_names.append(col)
                seen_cols.add(col)

    timestamps: list = []
    paths_out: list = []
    value_cols: dict[str, list] = {col: [] for col in all_col_names}
    unique_paths: set[str] = set()

    for row in data_rows:
        if not row:
            continue
        ts = row[0]
        for path in ordered_paths:
            methods = path_method_idx[path]
            is_array = path_is_array[path]
            cols = path_col_names[path]

            if is_array:
                arr_val = None
                for col_idx in methods.values():
                    i = col_idx + 1
                    if i < len(row) and row[i] is not None:
                        arr_val = row[i]
                        break
                if arr_val is None:
                    continue
                timestamps.append(ts)
                paths_out.append(path)
                unique_paths.add(path)
                row_vals: dict[str, str] = {c: "" for c in all_col_names}
                for j, col_name in enumerate(cols):
                    if j < len(arr_val):
                        row_vals[col_name] = str(arr_val[j])
                for col_name in all_col_names:
                    value_cols[col_name].append(row_vals[col_name])
            else:
                mn = _cell(row, methods["min"]) if "min" in methods else ""
                av = _cell(row, methods["average"]) if "average" in methods else ""
                mx = _cell(row, methods["max"]) if "max" in methods else ""
                if not mn and not av and not mx:
                    continue
                timestamps.append(ts)
                paths_out.append(path)
                unique_paths.add(path)
                row_vals = {c: "" for c in all_col_names}
                row_vals["min_value"] = mn
                row_vals["avg_value"] = av
                row_vals["max_value"] = mx
                for col_name in all_col_names:
                    value_cols[col_name].append(row_vals[col_name])

    return timestamps, paths_out, value_cols, unique_paths


def write_csv_wide(result: dict, sink, no_header: bool) -> tuple[int, set[str]]:
    """Write result as CSV with dynamic value columns (scalar: min/avg/max; array: named elements)."""
    timestamps, paths, value_cols, unique_paths = extract_rows_wide(result)
    col_names = list(value_cols.keys())
    writer = csv.writer(sink)
    if not no_header:
        writer.writerow(["timestamp", "path"] + col_names)
    for i, (ts, path) in enumerate(zip(timestamps, paths)):
        writer.writerow([ts, path] + [value_cols[col][i] for col in col_names])
    return len(timestamps), unique_paths


def write_feather_wide(result: dict, output: str) -> tuple[int, set[str]]:
    """Write result as Feather with dynamic value columns."""
    try:
        import pyarrow as pa
        import pyarrow.feather as feather
    except ImportError:
        raise ImportError(
            "pyarrow is required for Feather output: pip install 'signalk-cli[feather]'"
        ) from None
    timestamps, paths, value_cols, unique_paths = extract_rows_wide(result)
    table = pa.table(
        {
            "timestamp": pa.array(timestamps, type=pa.string()),
            "path": pa.array(paths, type=pa.string()),
            **{
                col: pa.array(vals, type=pa.string())
                for col, vals in value_cols.items()
            },
        }
    )
    feather.write_feather(table, output)
    return len(timestamps), unique_paths


def write_json(result: dict, sink, indent: int | None = None) -> tuple[int, set[str]]:
    """Write result as JSON array of row objects (narrow mode)."""
    timestamps, paths, values, unique_paths = extract_rows(result)
    rows = [
        {"timestamp": ts, "path": p, "value": v}
        for ts, p, v in zip(timestamps, paths, values)
    ]
    sink.write(json.dumps(rows, indent=indent))
    return len(rows), unique_paths


def write_json_wide(
    result: dict, sink, indent: int | None = None
) -> tuple[int, set[str]]:
    """Write result as JSON array of row objects (wide mode)."""
    timestamps, paths, value_cols, unique_paths = extract_rows_wide(result)
    col_names = list(value_cols.keys())
    rows = [
        {"timestamp": ts, "path": p, **{col: value_cols[col][i] for col in col_names}}
        for i, (ts, p) in enumerate(zip(timestamps, paths))
    ]
    sink.write(json.dumps(rows, indent=indent))
    return len(rows), unique_paths


# ---------------------------------------------------------------------------
# Cardinality
# ---------------------------------------------------------------------------

CARDINALITY_COLUMNS = [
    "path",
    "distinct_values",
    "distinct_values_2_decimal_places",
    "nulls",
    "zeroes",
    "min",
    "max",
    "average",
]


def compute_cardinality(result: dict) -> list[dict]:
    """Compute per-path value statistics from a narrow-mode API result.

    Each returned dict has keys matching CARDINALITY_COLUMNS.  min, max,
    average, and distinct_values_2_decimal_places are empty strings for
    non-scalar (array/dict) paths.
    """
    value_columns = result.get("values", [])
    data_rows = result.get("data", [])

    ordered_paths: list[str] = []
    path_col_idxs: dict[str, list[int]] = {}
    for i, col in enumerate(value_columns):
        path = col.get("path", f"col_{i}")
        if path not in path_col_idxs:
            ordered_paths.append(path)
            path_col_idxs[path] = []
        path_col_idxs[path].append(i)

    path_vals: dict[str, list] = {p: [] for p in ordered_paths}
    path_nulls: dict[str, int] = {p: 0 for p in ordered_paths}
    path_zeroes: dict[str, int] = {p: 0 for p in ordered_paths}

    for row in data_rows:
        if not row:
            continue
        for path, col_idxs in path_col_idxs.items():
            for col_idx in col_idxs:
                val = row[col_idx + 1] if col_idx + 1 < len(row) else None
                if val is None:
                    path_nulls[path] += 1
                else:
                    if (
                        isinstance(val, (int, float))
                        and not isinstance(val, bool)
                        and val == 0
                    ):
                        path_zeroes[path] += 1
                    path_vals[path].append(val)

    rows = []
    for path in ordered_paths:
        vals = path_vals[path]
        nulls = path_nulls[path]
        is_scalar = bool(vals) and all(
            isinstance(v, (int, float)) and not isinstance(v, bool) for v in vals
        )

        distinct = len(
            {
                json.dumps(v, sort_keys=True) if isinstance(v, (dict, list)) else str(v)
                for v in vals
            }
        )

        if not vals:
            mn = mx = avg = ""
            d2dp = "0"
        elif is_scalar:
            mn = str(min(vals))
            mx = str(max(vals))
            avg = str(sum(vals) / len(vals))
            d2dp = str(len({round(float(v), 2) for v in vals}))
        else:
            mn = mx = avg = ""
            if vals and isinstance(vals[0], list):
                d2dp = str(
                    len(
                        {
                            tuple(
                                round(x, 2)
                                if isinstance(x, (int, float))
                                and not isinstance(x, bool)
                                else x
                                for x in v
                            )
                            for v in vals
                        }
                    )
                )
            else:
                d2dp = ""

        rows.append(
            {
                "path": path,
                "distinct_values": str(distinct),
                "min": mn,
                "max": mx,
                "average": avg,
                "distinct_values_2_decimal_places": d2dp,
                "nulls": str(nulls),
                "zeroes": str(path_zeroes[path]),
            }
        )

    return rows


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
