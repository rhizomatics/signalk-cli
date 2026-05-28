"""Tests for output.py — CSV/Feather writers."""

import csv
import io


from signalk_cli.history.output import (
    compute_cardinality,
    extract_rows,
    extract_rows_wide,
    write_csv,
    write_csv_wide,
)
from tests.conftest import (
    CARDINALITY_NARROW_RESULT,
    CARDINALITY_POSITION_RESULT,
    GENERIC_ARRAY_WIDE_RESULT,
    MULTI_PATH_WIDE_RESULT,
    NARROW_RESULT,
    POSITION_WIDE_RESULT,
    WIDE_RESULT,
)


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
    ts, paths, value_cols, unique = extract_rows_wide(WIDE_RESULT)
    assert ts == ["2026-05-27T10:00:00Z", "2026-05-27T10:01:00Z"]
    assert value_cols["min_value"] == ["1.5", "1.0"]
    assert value_cols["avg_value"] == ["2.0", "1.5"]
    assert value_cols["max_value"] == ["2.5", "2.0"]
    assert unique == {"navigation.speedOverGround"}


def test_extract_rows_wide_column_order_is_min_avg_max():
    _, _, value_cols, _ = extract_rows_wide(WIDE_RESULT)
    assert list(value_cols.keys()) == ["min_value", "avg_value", "max_value"]
    assert (
        float(value_cols["min_value"][0])
        <= float(value_cols["avg_value"][0])
        <= float(value_cols["max_value"][0])
    )


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
    ts, paths, _value_cols, unique = extract_rows_wide(MULTI_PATH_WIDE_RESULT)
    assert len(ts) == 2
    assert set(paths) == {
        "navigation.speedOverGround",
        "navigation.courseOverGroundTrue",
    }
    assert unique == {"navigation.speedOverGround", "navigation.courseOverGroundTrue"}


def test_extract_rows_wide_position_col_names():
    ts, paths, value_cols, unique = extract_rows_wide(POSITION_WIDE_RESULT)
    assert list(value_cols.keys()) == ["longitude", "latitude"]
    assert ts == ["2026-05-27T10:00:00Z", "2026-05-27T10:01:00Z"]
    assert value_cols["longitude"] == ["51.5", "51.6"]
    assert value_cols["latitude"] == ["-0.1", "-0.2"]
    assert unique == {"navigation.position"}


def test_extract_rows_wide_generic_array_col_names():
    _, _, value_cols, _ = extract_rows_wide(GENERIC_ARRAY_WIDE_RESULT)
    assert list(value_cols.keys()) == ["value_0", "value_1", "value_2"]
    assert value_cols["value_0"] == ["10"]


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


# ---------------------------------------------------------------------------
# compute_cardinality
# ---------------------------------------------------------------------------


def test_compute_cardinality_scalar_stats() -> None:
    rows = compute_cardinality(CARDINALITY_NARROW_RESULT)
    assert len(rows) == 1
    r = rows[0]
    assert r["path"] == "navigation.speedOverGround"
    assert r["distinct_values"] == "3"  # 1.5, 2.0, 0.0
    assert r["min"] == "0.0"
    assert r["max"] == "2.0"
    assert r["nulls"] == "1"
    assert r["zeroes"] == "1"
    assert r["distinct_values_2_decimal_places"] == "3"


def test_compute_cardinality_average() -> None:
    rows = compute_cardinality(CARDINALITY_NARROW_RESULT)
    avg = float(rows[0]["average"])
    # (1.5 + 2.0 + 1.5 + 0.0) / 4
    assert abs(avg - (5.0 / 4)) < 1e-9


def test_compute_cardinality_non_scalar_skips_stats() -> None:
    rows = compute_cardinality(CARDINALITY_POSITION_RESULT)
    assert len(rows) == 1
    r = rows[0]
    assert r["path"] == "navigation.position"
    assert r["min"] == ""
    assert r["max"] == ""
    assert r["average"] == ""
    assert r["distinct_values_2_decimal_places"] == "2"
    assert r["distinct_values"] == "2"
    assert r["nulls"] == "1"


def test_compute_cardinality_2dp_deduplication() -> None:
    result = {
        "values": [{"path": "nav.sog"}],
        "data": [
            ["t1", 1.501],
            ["t2", 1.504],  # both round to 1.50
            ["t3", 1.510],  # rounds to 1.51
        ],
    }
    rows = compute_cardinality(result)
    assert rows[0]["distinct_values"] == "3"
    assert rows[0]["distinct_values_2_decimal_places"] == "2"


def test_compute_cardinality_array_2dp_rounds_elements() -> None:
    result = {
        "values": [{"path": "navigation.position"}],
        "data": [
            ["t1", [51.50001, -0.10001]],
            ["t2", [51.50002, -0.10002]],  # rounds to same as t1
            ["t3", [51.60000, -0.20000]],  # distinct after rounding
        ],
    }
    rows = compute_cardinality(result)
    assert rows[0]["distinct_values"] == "3"
    assert rows[0]["distinct_values_2_decimal_places"] == "2"


def test_compute_cardinality_no_values_gives_zero_d2dp() -> None:
    result = {
        "values": [{"path": "nav.sog"}],
        "data": [["t1", None], ["t2", None]],
    }
    rows = compute_cardinality(result)
    assert rows[0]["distinct_values"] == "0"
    assert rows[0]["distinct_values_2_decimal_places"] == "0"
    assert rows[0]["min"] == ""
    assert rows[0]["max"] == ""
    assert rows[0]["average"] == ""
