"""Row extraction and CSV/JSON/Feather writers for SignalK delta messages."""

import csv
import fnmatch
import json
from typing import IO

FEATHER_EXTENSIONS = {".feather", ".arrow", ".fea"}


def _normalize_value(value: object) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    if value is None:
        return ""
    return str(value)


def _update_source(update: dict) -> str:
    return update.get("$source") or json.dumps(update.get("source", {}))


def source_matches(source: str, patterns: tuple[str, ...]) -> bool:
    """Match a `$source` string against `--source` filter patterns (OR'd).

    No patterns means no filtering (always matches). A pattern containing
    glob metacharacters (`*`/`?`/`[`) is matched as-is via `fnmatch`;
    otherwise it's treated as a substring match, e.g. "Teltonika" matches
    the source "Teltonika.GP".
    """
    if not patterns:
        return True
    return any(
        fnmatch.fnmatch(source, p if any(c in p for c in "*?[") else f"*{p}*")
        for p in patterns
    )


def delta_matches_source(delta: dict, patterns: tuple[str, ...]) -> bool:
    """True if any update in the delta has a `$source` matching `patterns`.

    Used for `--format raw`, which echoes the whole message verbatim and so
    can only filter at message granularity, not per-update.
    """
    if not patterns:
        return True
    return any(
        source_matches(_update_source(update), patterns)
        for update in delta.get("updates", [])
    )


def extract_delta_rows(
    delta: dict, *, include_meta: bool = False, sources: tuple[str, ...] = ()
) -> list[tuple[str, ...]]:
    """Flatten a single delta message into rows.

    Without `include_meta`, rows are (timestamp, context, source, path,
    value) from each update's "values" entries. With `include_meta`, a
    "kind" column ("value"/"meta") is inserted before "value", and each
    update's "meta" entries are included too — per the Streaming API spec,
    "meta" entries have the same path/value shape but "value" is a metadata
    object (units, description, zones, etc.), not a telemetry reading.

    `sources`, if given, drops entire updates whose `$source` doesn't match
    any pattern (see `source_matches`) — filtering is per-update, since
    that's the granularity at which SignalK attaches a source.
    """
    context = delta.get("context", "")
    rows: list[tuple[str, ...]] = []
    for update in delta.get("updates", []):
        source = _update_source(update)
        if not source_matches(source, sources):
            continue
        timestamp = update.get("timestamp", "")
        for entry in update.get("values", []):
            path = entry.get("path", "")
            value = _normalize_value(entry.get("value"))
            if include_meta:
                rows.append((timestamp, context, source, path, "value", value))
            else:
                rows.append((timestamp, context, source, path, value))
        if include_meta:
            for entry in update.get("meta", []):
                path = entry.get("path", "")
                value = _normalize_value(entry.get("value"))
                rows.append((timestamp, context, source, path, "meta", value))
    return rows


CSV_COLUMNS = ["timestamp", "context", "source", "path", "value"]
CSV_COLUMNS_WITH_KIND = ["timestamp", "context", "source", "path", "kind", "value"]


def _columns(include_meta: bool) -> list[str]:
    return CSV_COLUMNS_WITH_KIND if include_meta else CSV_COLUMNS


def write_csv_header(sink: IO[str], *, include_meta: bool = False) -> None:
    csv.writer(sink).writerow(_columns(include_meta))
    sink.flush()


def write_csv_delta(
    delta: dict,
    sink: IO[str],
    *,
    include_meta: bool = False,
    sources: tuple[str, ...] = (),
) -> int:
    """Write one delta's rows as CSV lines. Returns the number of rows written."""
    rows = extract_delta_rows(delta, include_meta=include_meta, sources=sources)
    writer = csv.writer(sink)
    for row in rows:
        writer.writerow(row)
    sink.flush()
    return len(rows)


def write_json_delta(
    delta: dict,
    sink: IO[str],
    *,
    include_meta: bool = False,
    sources: tuple[str, ...] = (),
) -> int:
    """Write one delta's rows as JSON Lines (one row object per line). Returns row count."""
    rows = extract_delta_rows(delta, include_meta=include_meta, sources=sources)
    columns = _columns(include_meta)
    for row in rows:
        sink.write(json.dumps(dict(zip(columns, row))))
        sink.write("\n")
    sink.flush()
    return len(rows)


def write_values_delta(
    delta: dict,
    sink: IO[str],
    *,
    include_meta: bool = False,
    sources: tuple[str, ...] = (),
) -> int:
    """Write one delta's bare values, one per line — no other columns.

    For `--format values`: useful for piping a single path's readings
    straight into another tool/script. Returns the number of values written.
    """
    rows = extract_delta_rows(delta, include_meta=include_meta, sources=sources)
    for row in rows:
        sink.write(row[-1])
        sink.write("\n")
    sink.flush()
    return len(rows)


def write_feather_rows(
    rows: list[tuple[str, ...]], output: str, *, include_meta: bool = False
) -> int:
    """Write accumulated delta rows as Feather. Returns the number of rows written.

    Unlike CSV/JSON, Feather cannot be appended to incrementally — callers must
    buffer rows across messages and call this once at the end of the session.
    """
    try:
        import pyarrow as pa
        from pyarrow import feather
    except ImportError:
        raise ImportError(
            "pyarrow is required for Feather output: pip install 'signalk-cli[feather]'"
        ) from None
    columns = _columns(include_meta)
    row_columns = list(zip(*rows)) if rows else [()] * len(columns)
    table = pa.table(
        {
            name: pa.array(values, type=pa.string())
            for name, values in zip(columns, row_columns)
        }
    )
    feather.write_feather(table, output)
    return len(rows)
