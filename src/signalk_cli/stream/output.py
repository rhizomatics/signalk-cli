"""CSV, JSON Lines, bare-value and Feather writers for the stream CLI."""

import csv
import json
from collections.abc import Sequence
from typing import IO

from .._arrow import as_text
from .api import DeltaRow

CSV_COLUMNS = ["timestamp", "context", "source", "path", "value"]
CSV_COLUMNS_WITH_KIND = ["timestamp", "context", "source", "path", "kind", "value"]


def columns(include_meta: bool) -> list[str]:
    return CSV_COLUMNS_WITH_KIND if include_meta else CSV_COLUMNS


def _text_row(row: DeltaRow, include_meta: bool) -> list[str]:
    values = [row.timestamp, row.context, row.source, row.path]
    if include_meta:
        values.append(row.kind)
    values.append(as_text(row.value) or "")
    return values


def write_csv_header(sink: IO[str], *, include_meta: bool = False) -> None:
    csv.writer(sink).writerow(columns(include_meta))
    sink.flush()


def write_csv_rows(
    rows: Sequence[DeltaRow], sink: IO[str], *, include_meta: bool = False
) -> int:
    """Write rows as CSV lines. Returns the number of rows written."""
    writer = csv.writer(sink)
    for row in rows:
        writer.writerow(_text_row(row, include_meta))
    sink.flush()
    return len(rows)


def write_json_rows(
    rows: Sequence[DeltaRow], sink: IO[str], *, include_meta: bool = False
) -> int:
    """Write rows as JSON Lines (one row object per line). Returns row count."""
    cols = columns(include_meta)
    for row in rows:
        sink.write(json.dumps(dict(zip(cols, _text_row(row, include_meta)))))
        sink.write("\n")
    sink.flush()
    return len(rows)


def write_values_rows(rows: Sequence[DeltaRow], sink: IO[str]) -> int:
    """Write bare values, one per line — for piping one path's readings elsewhere."""
    for row in rows:
        sink.write(as_text(row.value) or "")
        sink.write("\n")
    sink.flush()
    return len(rows)
