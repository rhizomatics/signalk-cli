"""Reshape History API /values responses into long rows, wide rows, and per-path statistics.

Values keep their JSON types here (numbers, strings, objects, arrays); the CLI
writers and the Arrow conversion decide how to represent them.
"""

import json
import re
from typing import Any

POSITION_RE = re.compile(r"navigation.*\.position")

WIDE_SCALAR_COLUMNS = ["min_value", "avg_value", "max_value"]
_WIDE_METHOD_FOR_COLUMN = {
    "min_value": "min",
    "avg_value": "average",
    "max_value": "max",
}

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


def _is_number(v: object) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _cell(row: list, col_idx: int) -> Any:
    """Value at 0-based value column col_idx (row[0] is the timestamp), or None."""
    i = col_idx + 1
    return row[i] if i < len(row) else None


def _paths_by_column(payload: dict) -> list[str]:
    return [
        col.get("path", f"col_{i}") for i, col in enumerate(payload.get("values", []))
    ]


# ---------------------------------------------------------------------------
# Long: one row per (timestamp, path)
# ---------------------------------------------------------------------------


def long_rows(payload: dict) -> tuple[list[str], list[str], list[Any]]:
    """Flatten a /values response into (timestamps, paths, values), skipping nulls."""
    col_paths = _paths_by_column(payload)
    timestamps: list[str] = []
    paths: list[str] = []
    values: list[Any] = []
    for row in payload.get("data", []):
        if not row:
            continue
        for i, path in enumerate(col_paths):
            value = _cell(row, i)
            if value is None:
                continue
            timestamps.append(row[0])
            paths.append(path)
            values.append(value)
    return timestamps, paths, values


# ---------------------------------------------------------------------------
# Wide: one row per (timestamp, path) with min/avg/max or array element columns
# ---------------------------------------------------------------------------


def _first_value(data_rows: list, col_idx: int) -> Any:
    for row in data_rows:
        if row:
            v = _cell(row, col_idx)
            if v is not None:
                return v
    return None


def _array_col_names(path: str, length: int) -> list[str]:
    if length == 2 and POSITION_RE.fullmatch(path):
        return ["longitude", "latitude"]
    return [f"value_{i}" for i in range(length)]


def wide_rows(payload: dict) -> tuple[list[str], list[str], dict[str, list[Any]]]:
    """Reshape a /values response into (timestamps, paths, value_columns).

    Scalar paths fill `min_value`/`avg_value`/`max_value`. Array paths
    fill one column per element: `longitude`/`latitude` for
    `navigation.*.position`, otherwise `value_0`, `value_1`, ... Cells
    that don't apply to a row's path are None, and rows where every cell is
    null are dropped.
    """
    value_columns = payload.get("values", [])
    data_rows = payload.get("data", [])

    path_method_idx: dict[str, dict[str, int]] = {}
    for i, col in enumerate(value_columns):
        path = col.get("path", f"col_{i}")
        path_method_idx.setdefault(path, {})[col.get("method", "")] = i

    path_cols: dict[str, list[str]] = {}
    path_is_array: dict[str, bool] = {}
    for path, methods in path_method_idx.items():
        sample = None
        for col_idx in methods.values():
            sample = _first_value(data_rows, col_idx)
            if sample is not None:
                break
        path_is_array[path] = isinstance(sample, list)
        path_cols[path] = (
            _array_col_names(path, len(sample))
            if isinstance(sample, list)
            else WIDE_SCALAR_COLUMNS
        )

    all_cols: list[str] = []
    for cols in path_cols.values():
        all_cols.extend(c for c in cols if c not in all_cols)

    timestamps: list[str] = []
    paths_out: list[str] = []
    out: dict[str, list[Any]] = {c: [] for c in all_cols}

    for row in data_rows:
        if not row:
            continue
        for path, methods in path_method_idx.items():
            cells: dict[str, Any] = {}
            if path_is_array[path]:
                arr = next(
                    (
                        v
                        for v in (_cell(row, i) for i in methods.values())
                        if v is not None
                    ),
                    None,
                )
                if arr is None:
                    continue
                cells = dict(zip(path_cols[path], arr))
            else:
                cells = {
                    col: _cell(row, methods[method]) if method in methods else None
                    for col, method in _WIDE_METHOD_FOR_COLUMN.items()
                }
                if all(v is None for v in cells.values()):
                    continue
            timestamps.append(row[0])
            paths_out.append(path)
            for col in all_cols:
                out[col].append(cells.get(col))

    return timestamps, paths_out, out


# ---------------------------------------------------------------------------
# Cardinality
# ---------------------------------------------------------------------------


def _distinct_2dp(vals: list) -> int | None:
    if not vals:
        return 0
    if all(_is_number(v) for v in vals):
        return len({round(float(v), 2) for v in vals})
    if isinstance(vals[0], list):
        return len(
            {tuple(round(x, 2) if _is_number(x) else x for x in v) for v in vals}
        )
    return None


def cardinality(payload: dict) -> list[dict[str, Any]]:
    """Per-path statistics: distinct values, nulls, zeroes, and min/max/average.

    Each row has the keys in `CARDINALITY_COLUMNS`. `min`, `max` and
    `average` are None unless every value of the path is a number;
    `distinct_values_2_decimal_places` is None for paths whose values are
    neither numbers nor arrays.
    """
    col_paths = _paths_by_column(payload)
    ordered = list(dict.fromkeys(col_paths))
    vals: dict[str, list] = {p: [] for p in ordered}
    nulls = dict.fromkeys(ordered, 0)
    zeroes = dict.fromkeys(ordered, 0)

    for row in payload.get("data", []):
        if not row:
            continue
        for i, path in enumerate(col_paths):
            v = _cell(row, i)
            if v is None:
                nulls[path] += 1
                continue
            if _is_number(v) and v == 0:
                zeroes[path] += 1
            vals[path].append(v)

    rows = []
    for path in ordered:
        pv = vals[path]
        numeric = bool(pv) and all(_is_number(v) for v in pv)
        rows.append(
            {
                "path": path,
                "distinct_values": len(
                    {
                        json.dumps(v, sort_keys=True)
                        if isinstance(v, (dict, list))
                        else str(v)
                        for v in pv
                    }
                ),
                "distinct_values_2_decimal_places": _distinct_2dp(pv),
                "nulls": nulls[path],
                "zeroes": zeroes[path],
                "min": min(pv) if numeric else None,
                "max": max(pv) if numeric else None,
                "average": sum(pv) / len(pv) if numeric else None,
            }
        )
    return rows
