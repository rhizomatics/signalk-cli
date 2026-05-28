"""Tests for output.py — CSV/Feather writers."""

import csv
import io


from signalk_cli.history.output import (
    extract_rows,
    extract_rows_wide,
    write_csv,
    write_csv_wide,
)
from tests.conftest import MULTI_PATH_WIDE_RESULT, NARROW_RESULT, WIDE_RESULT


# ---------------------------------------------------------------------------
# extract_rows (narrow mode)
# ---------------------------------------------------------------------------


def test_extract_rows_basic():
    ts, paths, values, unique = extract_rows(NARROW_RESULT)
    assert ts == ["2026-05-27T10:00:00Z", "2026-05-27T10:01:00Z"]
    assert paths == ["navigation.speedOverGround", "navigation.speedOverGround"]
    assert values == ["1.5", "2.0"]
    assert unique == {"navigation.speedOverGround"}


def test_extract_rows_null_skipped():
    result = {
        "values": [{"path": "nav.sog"}, {"path": "nav.cog"}],
        "data": [
            ["2026-05-27T10:00:00Z", 1.5, None],
            ["2026-05-27T10:01:00Z", None, 90.0],
        ],
    }
    ts, paths, values, unique = extract_rows(result)
    assert paths == ["nav.sog", "nav.cog"]
    assert values == ["1.5", "90.0"]


def test_extract_rows_dict_value_json_encoded():
    result = {
        "values": [{"path": "navigation.position"}],
        "data": [["2026-05-27T10:00:00Z", {"latitude": 51.5, "longitude": -0.1}]],
    }
    _, _, values, _ = extract_rows(result)
    import json

    assert json.loads(values[0]) == {"latitude": 51.5, "longitude": -0.1}


def test_extract_rows_empty_data():
    ts, paths, values, unique = extract_rows({"values": [], "data": []})
    assert ts == [] and paths == [] and values == [] and unique == set()


# ---------------------------------------------------------------------------
# extract_rows_wide
# ---------------------------------------------------------------------------


def test_extract_rows_wide_basic():
    # Return order: (ts, paths, min_vals, max_vals, avg_vals, unique)
    ts, paths, min_v, max_v, avg_v, unique = extract_rows_wide(WIDE_RESULT)
    assert ts == ["2026-05-27T10:00:00Z", "2026-05-27T10:01:00Z"]
    assert min_v == ["1.5", "1.0"]
    assert avg_v == ["2.0", "1.5"]
    assert max_v == ["2.5", "2.0"]
    assert unique == {"navigation.speedOverGround"}


def test_extract_rows_wide_column_order_is_min_avg_max():
    _, _, min_v, max_v, avg_v, _ = extract_rows_wide(WIDE_RESULT)
    assert float(min_v[0]) <= float(avg_v[0]) <= float(max_v[0])


def test_extract_rows_wide_all_null_row_skipped():
    result = {
        "values": [
            {"path": "nav.sog", "method": "min"},
            {"path": "nav.sog", "method": "average"},
            {"path": "nav.sog", "method": "max"},
        ],
        "data": [
            ["2026-05-27T10:00:00Z", None, None, None],
            ["2026-05-27T10:01:00Z", 1.0, 1.5, 2.0],
        ],
    }
    ts, *_ = extract_rows_wide(result)
    assert len(ts) == 1
    assert ts[0] == "2026-05-27T10:01:00Z"


def test_extract_rows_wide_multi_path():
    ts, paths, *_, unique = extract_rows_wide(MULTI_PATH_WIDE_RESULT)
    assert len(ts) == 2
    assert set(paths) == {
        "navigation.speedOverGround",
        "navigation.courseOverGroundTrue",
    }
    assert unique == {"navigation.speedOverGround", "navigation.courseOverGroundTrue"}


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
