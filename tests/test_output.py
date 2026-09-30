"""Tests for history/output.py — CLI writers."""

import csv
import io
import json

import pytest

from signalk_cli._arrow import write_feather
from signalk_cli.history.api import HistoryResult
from signalk_cli.history.output import (
    cardinality_text,
    write_csv,
    write_csv_wide,
    write_json,
    write_json_wide,
)
from tests.conftest import (
    NARROW_RESULT,
    POSITION_WIDE_RESULT,
    WIDE_RESULT,
)

# ---------------------------------------------------------------------------
# write_csv / write_csv_wide
# ---------------------------------------------------------------------------


def _csv_rows(result, wide=False, no_header=False):
    buf = io.StringIO()
    if wide:
        write_csv_wide(result, buf, no_header)
    else:
        write_csv(result, buf, no_header)
    buf.seek(0)
    return list(csv.reader(buf))


def test_write_csv_header_row():
    rows = _csv_rows(NARROW_RESULT)
    assert rows[0] == ["timestamp", "path", "value"]


def test_write_csv_no_header():
    rows = _csv_rows(NARROW_RESULT, no_header=True)
    assert rows[0][0] == "2026-05-27T10:00:00Z"


def test_write_csv_data_rows():
    rows = _csv_rows(NARROW_RESULT)
    assert rows[1] == ["2026-05-27T10:00:00Z", "navigation.speedOverGround", "1.5"]
    assert rows[2] == ["2026-05-27T10:01:00Z", "navigation.speedOverGround", "2.0"]


def test_write_csv_wide_header_order():
    rows = _csv_rows(WIDE_RESULT, wide=True)
    assert rows[0] == ["timestamp", "path", "min_value", "avg_value", "max_value"]


def test_write_csv_wide_values():
    rows = _csv_rows(WIDE_RESULT, wide=True)
    assert rows[1] == [
        "2026-05-27T10:00:00Z",
        "navigation.speedOverGround",
        "1.5",
        "2.0",
        "2.5",
    ]


def test_write_csv_wide_row_count():
    rows = _csv_rows(WIDE_RESULT, wide=True)
    assert len(rows) == 3  # header + 2 data rows


def test_write_csv_wide_position_header():
    rows = _csv_rows(POSITION_WIDE_RESULT, wide=True)
    assert rows[0] == ["timestamp", "path", "longitude", "latitude"]


def test_write_csv_wide_position_values():
    rows = _csv_rows(POSITION_WIDE_RESULT, wide=True)
    assert rows[1] == ["2026-05-27T10:00:00Z", "navigation.position", "51.5", "-0.1"]
    assert rows[2] == ["2026-05-27T10:01:00Z", "navigation.position", "51.6", "-0.2"]


def test_write_csv_json_encodes_objects():
    result = {
        "values": [{"path": "navigation.position"}],
        "data": [["2026-05-27T10:00:00Z", {"latitude": 51.5, "longitude": -0.1}]],
    }
    rows = _csv_rows(result)
    assert json.loads(rows[1][2]) == {"latitude": 51.5, "longitude": -0.1}


def test_write_csv_returns_counts():
    count, paths = write_csv(NARROW_RESULT, io.StringIO(), no_header=False)
    assert (count, paths) == (2, {"navigation.speedOverGround"})


# ---------------------------------------------------------------------------
# write_json / write_json_wide
# ---------------------------------------------------------------------------


def test_write_json_rows_are_text():
    buf = io.StringIO()
    count, _ = write_json(NARROW_RESULT, buf)
    assert count == 2
    assert json.loads(buf.getvalue())[0] == {
        "timestamp": "2026-05-27T10:00:00Z",
        "path": "navigation.speedOverGround",
        "value": "1.5",
    }


def test_write_json_indent():
    buf = io.StringIO()
    write_json(NARROW_RESULT, buf, indent=2)
    assert buf.getvalue().startswith("[\n  {")


def test_write_json_wide_columns():
    buf = io.StringIO()
    write_json_wide(WIDE_RESULT, buf)
    assert json.loads(buf.getvalue())[0] == {
        "timestamp": "2026-05-27T10:00:00Z",
        "path": "navigation.speedOverGround",
        "min_value": "1.5",
        "avg_value": "2.0",
        "max_value": "2.5",
    }


def test_write_json_wide_blank_for_other_paths_columns():
    result = {
        "values": [
            {"path": "navigation.position", "method": "mid"},
            {"path": "nav.sog", "method": "min"},
        ],
        "data": [["2026-05-27T10:00:00Z", [51.5, -0.1], 1.0]],
    }
    buf = io.StringIO()
    write_json_wide(result, buf)
    rows = json.loads(buf.getvalue())
    assert rows[0]["min_value"] == ""
    assert rows[1]["longitude"] == ""


# ---------------------------------------------------------------------------
# write_feather
# ---------------------------------------------------------------------------


def test_write_feather_typed_columns(tmp_path):
    pa = pytest.importorskip("pyarrow")
    from pyarrow import feather

    out = tmp_path / "wide.feather"
    write_feather(HistoryResult(WIDE_RESULT, wide=True).to_arrow(), str(out))
    table = feather.read_table(out)
    assert table.column_names == [
        "timestamp",
        "path",
        "min_value",
        "avg_value",
        "max_value",
    ]
    assert table.schema.field("timestamp").type == pa.timestamp("us", tz="UTC")
    assert table.schema.field("min_value").type == pa.float64()
    assert table.column("min_value").to_pylist() == [1.5, 1.0]


def test_write_feather_without_pyarrow(monkeypatch, tmp_path):
    import builtins

    real_import = builtins.__import__

    def _no_pyarrow(name, *args, **kwargs):
        if name.startswith("pyarrow"):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_pyarrow)
    with pytest.raises(ImportError, match=r"signalk-cli\[feather\]"):
        write_feather(HistoryResult(NARROW_RESULT).to_arrow(), str(tmp_path / "x"))


# ---------------------------------------------------------------------------
# cardinality_text
# ---------------------------------------------------------------------------


def test_cardinality_text_blanks_missing_stats():
    row = {
        "path": "navigation.position",
        "distinct_values": 2,
        "distinct_values_2_decimal_places": None,
        "nulls": 0,
        "zeroes": 0,
        "min": None,
        "max": None,
        "average": None,
    }
    assert cardinality_text(row) == {
        "path": "navigation.position",
        "distinct_values": "2",
        "distinct_values_2_decimal_places": "",
        "nulls": "0",
        "zeroes": "0",
        "min": "",
        "max": "",
        "average": "",
    }
