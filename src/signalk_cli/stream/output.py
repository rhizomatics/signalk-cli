"""Row extraction and CSV/JSON/Feather writers for SignalK delta messages."""

import csv
import json
from typing import IO

FEATHER_EXTENSIONS = {".feather", ".arrow", ".fea"}


def extract_delta_rows(delta: dict) -> list[tuple[str, str, str, str, str]]:
    """Flatten a single delta message into (timestamp, context, source, path, value) rows."""
    context = delta.get("context", "")
    rows = []
    for update in delta.get("updates", []):
        timestamp = update.get("timestamp", "")
        source = update.get("$source") or json.dumps(update.get("source", {}))
        for entry in update.get("values", []):
            path = entry.get("path", "")
            value = entry.get("value")
            if isinstance(value, (dict, list)):
                value = json.dumps(value)
            elif value is None:
                value = ""
            else:
                value = str(value)
            rows.append((timestamp, context, source, path, value))
    return rows


CSV_COLUMNS = ["timestamp", "context", "source", "path", "value"]


def write_csv_header(sink: IO[str]) -> None:
    csv.writer(sink).writerow(CSV_COLUMNS)
    sink.flush()


def write_csv_delta(delta: dict, sink: IO[str]) -> int:
    """Write one delta's rows as CSV lines. Returns the number of rows written."""
    rows = extract_delta_rows(delta)
    writer = csv.writer(sink)
    for row in rows:
        writer.writerow(row)
    sink.flush()
    return len(rows)


def write_json_delta(delta: dict, sink: IO[str]) -> int:
    """Write one delta's rows as JSON Lines (one row object per line). Returns row count."""
    rows = extract_delta_rows(delta)
    for ts, context, source, path, value in rows:
        sink.write(
            json.dumps(
                {
                    "timestamp": ts,
                    "context": context,
                    "source": source,
                    "path": path,
                    "value": value,
                }
            )
        )
        sink.write("\n")
    sink.flush()
    return len(rows)


def write_feather_rows(rows: list[tuple[str, str, str, str, str]], output: str) -> int:
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
    columns = list(zip(*rows)) if rows else [()] * len(CSV_COLUMNS)
    table = pa.table(
        {
            name: pa.array(values, type=pa.string())
            for name, values in zip(CSV_COLUMNS, columns)
        }
    )
    feather.write_feather(table, output)
    return len(rows)
