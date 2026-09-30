"""Tests for stream/output.py — CSV/JSON Lines/values writers."""

import io
import json

from signalk_cli.stream.api import DeltaMessage
from signalk_cli.stream.output import (
    write_csv_header,
    write_csv_rows,
    write_json_rows,
    write_values_rows,
)
from tests.conftest import (
    DELTA_MULTI_SOURCE,
    DELTA_MULTI_VALUE,
    DELTA_SINGLE_VALUE,
    DELTA_WITH_META,
)


def _rows(payload, **kwargs):
    return DeltaMessage(json.dumps(payload), payload).rows(**kwargs)


# ---------------------------------------------------------------------------
# write_values_rows
# ---------------------------------------------------------------------------


def test_write_values_rows_writes_bare_values():
    sink = io.StringIO()
    count = write_values_rows(_rows(DELTA_MULTI_VALUE), sink)
    assert count == 2
    assert sink.getvalue() == '{"latitude": 51.5, "longitude": -0.1}\n\n'


def test_write_values_rows_filters_by_source():
    sink = io.StringIO()
    count = write_values_rows(_rows(DELTA_MULTI_SOURCE, sources=("Teltonika",)), sink)
    assert count == 1
    assert sink.getvalue() == "1.5\n"


# ---------------------------------------------------------------------------
# write_csv_header / write_csv_rows
# ---------------------------------------------------------------------------


def test_write_csv_header():
    sink = io.StringIO()
    write_csv_header(sink)
    assert sink.getvalue() == "timestamp,context,source,path,value\r\n"


def test_write_csv_header_include_meta():
    sink = io.StringIO()
    write_csv_header(sink, include_meta=True)
    assert sink.getvalue() == "timestamp,context,source,path,kind,value\r\n"


def test_write_csv_rows_row_count_and_content():
    sink = io.StringIO()
    count = write_csv_rows(_rows(DELTA_SINGLE_VALUE), sink)
    assert count == 1
    assert "navigation.speedOverGround" in sink.getvalue()
    assert "1.5" in sink.getvalue()


def test_write_csv_rows_include_meta():
    sink = io.StringIO()
    count = write_csv_rows(
        _rows(DELTA_WITH_META, include_meta=True), sink, include_meta=True
    )
    assert count == 2
    assert ",meta," in sink.getvalue()


def test_write_csv_rows_filters_by_source():
    sink = io.StringIO()
    count = write_csv_rows(_rows(DELTA_MULTI_SOURCE, sources=("derived-data",)), sink)
    assert count == 1
    assert "derived-data" in sink.getvalue()
    assert "Teltonika" not in sink.getvalue()


# ---------------------------------------------------------------------------
# write_json_rows
# ---------------------------------------------------------------------------


def test_write_json_rows_writes_json_lines():
    sink = io.StringIO()
    count = write_json_rows(_rows(DELTA_MULTI_VALUE), sink)
    assert count == 2
    lines = sink.getvalue().splitlines()
    assert len(lines) == 2
    row0 = json.loads(lines[0])
    assert row0["path"] == "navigation.position"
    assert row0["context"] == "vessels.self"


def test_write_json_rows_include_meta():
    sink = io.StringIO()
    count = write_json_rows(
        _rows(DELTA_WITH_META, include_meta=True), sink, include_meta=True
    )
    assert count == 2
    lines = [json.loads(line) for line in sink.getvalue().splitlines()]
    assert [row["kind"] for row in lines] == ["value", "meta"]
