"""Tests for stream/output.py — delta row extraction and CSV/JSON/Feather writers."""

import io
import json

import pytest

from signalk_cli.stream.output import (
    delta_matches_source,
    extract_delta_rows,
    source_matches,
    write_csv_delta,
    write_csv_header,
    write_feather_rows,
    write_json_delta,
    write_values_delta,
)
from tests.conftest import (
    DELTA_MULTI_SOURCE,
    DELTA_MULTI_VALUE,
    DELTA_SINGLE_VALUE,
    DELTA_WITH_META,
)

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
    _ts, context, source, path, value = rows[0]
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


def test_extract_delta_rows_ignores_meta_by_default():
    rows = extract_delta_rows(DELTA_WITH_META)
    assert len(rows) == 1
    assert rows[0][3] == "navigation.speedOverGround"
    assert rows[0][4] == "2.5"


def test_extract_delta_rows_include_meta_adds_kind_and_meta_rows():
    rows = extract_delta_rows(DELTA_WITH_META, include_meta=True)
    assert len(rows) == 2
    _ts, _context, _source, path, kind, value = rows[0]
    assert (path, kind, value) == ("navigation.speedOverGround", "value", "2.5")
    _ts, _context, _source, path, kind, value = rows[1]
    assert path == "navigation.speedOverGround"
    assert kind == "meta"
    assert json.loads(value) == {"units": "m/s", "description": "Speed over ground"}


def test_extract_delta_rows_filters_by_source_substring():
    rows = extract_delta_rows(DELTA_MULTI_SOURCE, sources=("Teltonika",))
    assert len(rows) == 1
    assert rows[0][2] == "Teltonika.GP"


def test_extract_delta_rows_filters_by_source_glob():
    rows = extract_delta_rows(DELTA_MULTI_SOURCE, sources=("*.GP",))
    assert len(rows) == 1
    assert rows[0][2] == "Teltonika.GP"


def test_extract_delta_rows_multiple_source_patterns_are_ored():
    rows = extract_delta_rows(DELTA_MULTI_SOURCE, sources=("Teltonika", "derived-data"))
    assert len(rows) == 2


def test_extract_delta_rows_no_matching_source_yields_no_rows():
    rows = extract_delta_rows(DELTA_MULTI_SOURCE, sources=("no-such-source",))
    assert rows == []


# ---------------------------------------------------------------------------
# source_matches / delta_matches_source
# ---------------------------------------------------------------------------


def test_source_matches_no_patterns_matches_anything():
    assert source_matches("anything", ())


def test_source_matches_substring():
    assert source_matches("Teltonika.GP", ("Teltonika",))
    assert not source_matches("derived-data", ("Teltonika",))


def test_source_matches_glob():
    assert source_matches("Teltonika.GP", ("*.GP",))
    assert not source_matches("derived-data", ("*.GP",))


def test_delta_matches_source_true_if_any_update_matches():
    assert delta_matches_source(DELTA_MULTI_SOURCE, ("derived-data",))


def test_delta_matches_source_false_if_no_update_matches():
    assert not delta_matches_source(DELTA_MULTI_SOURCE, ("no-such-source",))


# ---------------------------------------------------------------------------
# write_values_delta
# ---------------------------------------------------------------------------


def test_write_values_delta_writes_bare_values():
    sink = io.StringIO()
    count = write_values_delta(DELTA_MULTI_VALUE, sink)
    assert count == 2
    assert sink.getvalue() == '{"latitude": 51.5, "longitude": -0.1}\n\n'


def test_write_values_delta_filters_by_source():
    sink = io.StringIO()
    count = write_values_delta(DELTA_MULTI_SOURCE, sink, sources=("Teltonika",))
    assert count == 1
    assert sink.getvalue() == "1.5\n"


# ---------------------------------------------------------------------------
# write_csv_header / write_csv_delta
# ---------------------------------------------------------------------------


def test_write_csv_header():
    sink = io.StringIO()
    write_csv_header(sink)
    assert sink.getvalue() == "timestamp,context,source,path,value\r\n"


def test_write_csv_header_include_meta():
    sink = io.StringIO()
    write_csv_header(sink, include_meta=True)
    assert sink.getvalue() == "timestamp,context,source,path,kind,value\r\n"


def test_write_csv_delta_row_count_and_content():
    sink = io.StringIO()
    count = write_csv_delta(DELTA_SINGLE_VALUE, sink)
    assert count == 1
    assert "navigation.speedOverGround" in sink.getvalue()
    assert "1.5" in sink.getvalue()


def test_write_csv_delta_include_meta():
    sink = io.StringIO()
    count = write_csv_delta(DELTA_WITH_META, sink, include_meta=True)
    assert count == 2
    assert ",meta," in sink.getvalue()


def test_write_csv_delta_filters_by_source():
    sink = io.StringIO()
    count = write_csv_delta(DELTA_MULTI_SOURCE, sink, sources=("derived-data",))
    assert count == 1
    assert "derived-data" in sink.getvalue()
    assert "Teltonika" not in sink.getvalue()


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


def test_write_json_delta_include_meta():
    sink = io.StringIO()
    count = write_json_delta(DELTA_WITH_META, sink, include_meta=True)
    assert count == 2
    lines = [json.loads(line) for line in sink.getvalue().splitlines()]
    assert [row["kind"] for row in lines] == ["value", "meta"]


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


def test_write_feather_rows_include_meta(tmp_path):
    feather = pytest.importorskip("pyarrow.feather")

    rows = extract_delta_rows(DELTA_WITH_META, include_meta=True)
    out_file = tmp_path / "meta.feather"
    count = write_feather_rows(rows, str(out_file), include_meta=True)

    assert count == 2
    table = feather.read_table(out_file)
    assert table.column_names == [
        "timestamp",
        "context",
        "source",
        "path",
        "kind",
        "value",
    ]
    assert table.column("kind").to_pylist() == ["value", "meta"]


def test_write_feather_rows_empty(tmp_path):
    feather = pytest.importorskip("pyarrow.feather")

    out_file = tmp_path / "empty.feather"
    count = write_feather_rows([], str(out_file))

    assert count == 0
    table = feather.read_table(out_file)
    assert table.num_rows == 0
