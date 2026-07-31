"""Tests for stream/output.py — delta row extraction and CSV/JSON/Feather writers."""

import io
import json

import pytest

from signalk_cli.stream.output import (
    extract_delta_rows,
    write_csv_delta,
    write_csv_header,
    write_feather_rows,
    write_json_delta,
)
from tests.conftest import DELTA_MULTI_VALUE, DELTA_SINGLE_VALUE

# ---------------------------------------------------------------------------
# extract_delta_rows
# ---------------------------------------------------------------------------


def test_extract_delta_rows_single_value():
    rows = extract_delta_rows(DELTA_SINGLE_VALUE)
    assert rows == [
        (
            "2026-07-31T15:38:08.041Z",
            "vessels.urn:mrn:imo:mmsi:235094115",
            "Teltonika.GP",
            "navigation.speedOverGround",
            "1.5",
        )
    ]


def test_extract_delta_rows_multi_value_dict_and_none():
    rows = extract_delta_rows(DELTA_MULTI_VALUE)
    assert len(rows) == 2
    ts, context, source, path, value = rows[0]
    assert context == "vessels.self"
    assert source == "derived-data"
    assert path == "navigation.position"
    assert json.loads(value) == {"latitude": 51.5, "longitude": -0.1}
    assert rows[1][3] == "navigation.courseOverGroundTrue"
    assert rows[1][4] == ""


def test_extract_delta_rows_falls_back_to_source_object():
    delta = {
        "context": "vessels.self",
        "updates": [
            {
                "source": {"label": "gps0"},
                "timestamp": "t",
                "values": [{"path": "p", "value": 1}],
            }
        ],
    }
    rows = extract_delta_rows(delta)
    assert json.loads(rows[0][2]) == {"label": "gps0"}


# ---------------------------------------------------------------------------
# write_csv_header / write_csv_delta
# ---------------------------------------------------------------------------


def test_write_csv_header():
    sink = io.StringIO()
    write_csv_header(sink)
    assert sink.getvalue() == "timestamp,context,source,path,value\r\n"


def test_write_csv_delta_row_count_and_content():
    sink = io.StringIO()
    count = write_csv_delta(DELTA_SINGLE_VALUE, sink)
    assert count == 1
    assert "navigation.speedOverGround" in sink.getvalue()
    assert "1.5" in sink.getvalue()


# ---------------------------------------------------------------------------
# write_json_delta
# ---------------------------------------------------------------------------


def test_write_json_delta_writes_json_lines():
    sink = io.StringIO()
    count = write_json_delta(DELTA_MULTI_VALUE, sink)
    assert count == 2
    lines = sink.getvalue().splitlines()
    assert len(lines) == 2
    row0 = json.loads(lines[0])
    assert row0["path"] == "navigation.position"
    assert row0["context"] == "vessels.self"


# ---------------------------------------------------------------------------
# write_feather_rows
# ---------------------------------------------------------------------------


def test_write_feather_rows_missing_pyarrow(mocker):
    mocker.patch.dict("sys.modules", {"pyarrow": None, "pyarrow.feather": None})
    with pytest.raises(ImportError, match="signalk-cli\\[feather\\]"):
        write_feather_rows(extract_delta_rows(DELTA_SINGLE_VALUE), "out.feather")


def test_write_feather_rows_writes_table(tmp_path):
    feather = pytest.importorskip("pyarrow.feather")

    rows = extract_delta_rows(DELTA_SINGLE_VALUE) + extract_delta_rows(
        DELTA_MULTI_VALUE
    )
    out_file = tmp_path / "out.feather"
    count = write_feather_rows(rows, str(out_file))

    assert count == len(rows)
    table = feather.read_table(out_file)
    assert table.num_rows == len(rows)
    assert table.column_names == ["timestamp", "context", "source", "path", "value"]
    assert table.column("path").to_pylist() == [r[3] for r in rows]


def test_write_feather_rows_empty(tmp_path):
    feather = pytest.importorskip("pyarrow.feather")

    out_file = tmp_path / "empty.feather"
    count = write_feather_rows([], str(out_file))

    assert count == 0
    table = feather.read_table(out_file)
    assert table.num_rows == 0
