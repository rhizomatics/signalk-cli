"""Tests for history._results — reshaping /values responses."""

from signalk_cli.history._results import cardinality, long_rows, wide_rows
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
# long_rows
# ---------------------------------------------------------------------------


def test_long_rows_basic():
    ts, paths, values = long_rows(NARROW_RESULT)
    assert ts == ["2026-05-27T10:00:00Z", "2026-05-27T10:01:00Z"]
    assert paths == ["navigation.speedOverGround", "navigation.speedOverGround"]
    assert values == [1.5, 2.0]


def test_long_rows_null_skipped():
    result = {
        "values": [{"path": "nav.sog"}, {"path": "nav.cog"}],
        "data": [
            ["2026-05-27T10:00:00Z", 1.5, None],
            ["2026-05-27T10:01:00Z", None, 90.0],
        ],
    }
    _ts, paths, values = long_rows(result)
    assert paths == ["nav.sog", "nav.cog"]
    assert values == [1.5, 90.0]


def test_long_rows_dict_value_json_encoded():
    result = {
        "values": [{"path": "navigation.position"}],
        "data": [["2026-05-27T10:00:00Z", {"latitude": 51.5, "longitude": -0.1}]],
    }
    _, _, values = long_rows(result)
    assert values[0] == {"latitude": 51.5, "longitude": -0.1}


def test_long_rows_empty_data():
    ts, paths, values = long_rows({"values": [], "data": []})
    assert ts == [] and paths == [] and values == []


# ---------------------------------------------------------------------------
# wide_rows
# ---------------------------------------------------------------------------


def test_wide_rows_basic():
    ts, paths, value_cols = wide_rows(WIDE_RESULT)
    assert ts == ["2026-05-27T10:00:00Z", "2026-05-27T10:01:00Z"]
    assert value_cols["min_value"] == [1.5, 1.0]
    assert value_cols["avg_value"] == [2.0, 1.5]
    assert value_cols["max_value"] == [2.5, 2.0]
    assert set(paths) == {"navigation.speedOverGround"}


def test_wide_rows_column_order_is_min_avg_max():
    _, _, value_cols = wide_rows(WIDE_RESULT)
    assert list(value_cols.keys()) == ["min_value", "avg_value", "max_value"]
    assert (
        value_cols["min_value"][0]
        <= value_cols["avg_value"][0]
        <= value_cols["max_value"][0]
    )


def test_wide_rows_all_null_row_skipped():
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
    ts, *_ = wide_rows(result)
    assert len(ts) == 1
    assert ts[0] == "2026-05-27T10:01:00Z"


def test_wide_rows_multi_path():
    ts, paths, _value_cols = wide_rows(MULTI_PATH_WIDE_RESULT)
    assert len(ts) == 2
    assert set(paths) == {
        "navigation.speedOverGround",
        "navigation.courseOverGroundTrue",
    }


def test_wide_rows_position_col_names():
    ts, paths, value_cols = wide_rows(POSITION_WIDE_RESULT)
    assert list(value_cols.keys()) == ["longitude", "latitude"]
    assert ts == ["2026-05-27T10:00:00Z", "2026-05-27T10:01:00Z"]
    assert value_cols["longitude"] == [51.5, 51.6]
    assert value_cols["latitude"] == [-0.1, -0.2]
    assert set(paths) == {"navigation.position"}


def test_wide_rows_generic_array_col_names():
    _, _, value_cols = wide_rows(GENERIC_ARRAY_WIDE_RESULT)
    assert list(value_cols.keys()) == ["value_0", "value_1", "value_2"]
    assert value_cols["value_0"] == [10]


# ---------------------------------------------------------------------------
# cardinality
# ---------------------------------------------------------------------------


def test_cardinality_scalar_stats() -> None:
    rows = cardinality(CARDINALITY_NARROW_RESULT)
    assert len(rows) == 1
    r = rows[0]
    assert r["path"] == "navigation.speedOverGround"
    assert r["distinct_values"] == 3  # 1.5, 2.0, 0.0
    assert r["min"] == 0.0
    assert r["max"] == 2.0
    assert r["nulls"] == 1
    assert r["zeroes"] == 1
    assert r["distinct_values_2_decimal_places"] == 3


def test_cardinality_average() -> None:
    rows = cardinality(CARDINALITY_NARROW_RESULT)
    avg = rows[0]["average"]
    # (1.5 + 2.0 + 1.5 + 0.0) / 4
    assert abs(avg - (5.0 / 4)) < 1e-9


def test_cardinality_non_scalar_skips_stats() -> None:
    rows = cardinality(CARDINALITY_POSITION_RESULT)
    assert len(rows) == 1
    r = rows[0]
    assert r["path"] == "navigation.position"
    assert r["min"] is None
    assert r["max"] is None
    assert r["average"] is None
    assert r["distinct_values_2_decimal_places"] == 2
    assert r["distinct_values"] == 2
    assert r["nulls"] == 1


def test_cardinality_2dp_deduplication() -> None:
    result = {
        "values": [{"path": "nav.sog"}],
        "data": [
            ["t1", 1.501],
            ["t2", 1.504],  # both round to 1.50
            ["t3", 1.510],  # rounds to 1.51
        ],
    }
    rows = cardinality(result)
    assert rows[0]["distinct_values"] == 3
    assert rows[0]["distinct_values_2_decimal_places"] == 2


def test_cardinality_array_2dp_rounds_elements() -> None:
    result = {
        "values": [{"path": "navigation.position"}],
        "data": [
            ["t1", [51.50001, -0.10001]],
            ["t2", [51.50002, -0.10002]],  # rounds to same as t1
            ["t3", [51.60000, -0.20000]],  # distinct after rounding
        ],
    }
    rows = cardinality(result)
    assert rows[0]["distinct_values"] == 3
    assert rows[0]["distinct_values_2_decimal_places"] == 2


def test_cardinality_no_values_gives_zero_d2dp() -> None:
    result = {
        "values": [{"path": "nav.sog"}],
        "data": [["t1", None], ["t2", None]],
    }
    rows = cardinality(result)
    assert rows[0]["distinct_values"] == 0
    assert rows[0]["distinct_values_2_decimal_places"] == 0
    assert rows[0]["min"] is None
    assert rows[0]["max"] is None
    assert rows[0]["average"] is None
