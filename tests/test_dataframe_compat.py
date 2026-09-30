"""ArrowTable loads into each supported dataframe library via the Arrow PyCapsule interface.

These guard the library API's main promise: no pyarrow dependency, yet tables
load with the right types everywhere.
"""

import datetime as dt
import json
from collections.abc import Callable
from typing import Any

import pytest

from signalk_cli._arrow import ArrowTable
from signalk_cli.history.api import HistoryResult
from signalk_cli.stream.api import DeltaMessage, rows_to_arrow
from tests.conftest import (
    DELTA_MULTI_VALUE,
    NARROW_RESULT,
    POSITION_WIDE_RESULT,
    WIDE_RESULT,
)


def _polars(table: ArrowTable) -> list[dict[str, Any]]:
    pl = pytest.importorskip("polars")
    return pl.DataFrame(table).to_dicts()


def _pandas(table: ArrowTable) -> list[dict[str, Any]]:
    pd = pytest.importorskip("pandas")
    df = pd.DataFrame.from_arrow(table)
    records = df.astype(object).where(df.notna(), None).to_dict("records")
    return [
        {
            k: v.to_pydatetime() if hasattr(v, "to_pydatetime") else v
            for k, v in r.items()
        }
        for r in records
    ]


def _duckdb(table: ArrowTable) -> list[dict[str, Any]]:
    duckdb = pytest.importorskip("duckdb")
    rel = duckdb.from_arrow(table)
    if "timestamp" in rel.columns:
        # Fetching TIMESTAMPTZ into Python needs pytz; convert to UTC in DuckDB instead
        rel = duckdb.sql(
            "select * replace (timezone('UTC', timestamp) as timestamp) from rel"
        )
    rows = [dict(zip(rel.columns, row)) for row in rel.fetchall()]
    for r in rows:
        if isinstance(r.get("timestamp"), dt.datetime):
            r["timestamp"] = r["timestamp"].replace(tzinfo=dt.UTC)
    return rows


def _pyarrow(table: ArrowTable) -> list[dict[str, Any]]:
    pa = pytest.importorskip("pyarrow")
    return pa.table(table).to_pylist()


LOADERS: dict[str, Callable[[ArrowTable], list[dict[str, Any]]]] = {
    "polars": _polars,
    "pandas": _pandas,
    "duckdb": _duckdb,
    "pyarrow": _pyarrow,
}

T0 = dt.datetime(2026, 5, 27, 10, 0, tzinfo=dt.UTC)
T1 = dt.datetime(2026, 5, 27, 10, 1, tzinfo=dt.UTC)


def _same_instant(a: dt.datetime, b: dt.datetime) -> bool:
    return a.astimezone(dt.UTC) == b


@pytest.fixture(params=list(LOADERS))
def load(request):
    return LOADERS[request.param]


def test_wide_history_table(load):
    rows = load(HistoryResult(WIDE_RESULT, wide=True).to_arrow())
    assert [r["avg_value"] for r in rows] == [2.0, 1.5]
    assert rows[0]["path"] == "navigation.speedOverGround"
    assert _same_instant(rows[0]["timestamp"], T0)
    assert _same_instant(rows[1]["timestamp"], T1)


def test_long_history_table(load):
    rows = load(HistoryResult(NARROW_RESULT).to_arrow())
    assert [r["value"] for r in rows] == [1.5, 2.0]
    assert isinstance(rows[0]["value"], float)


def test_position_columns(load):
    rows = load(HistoryResult(POSITION_WIDE_RESULT, wide=True).to_arrow())
    assert [(r["longitude"], r["latitude"]) for r in rows] == [
        (51.5, -0.1),
        (51.6, -0.2),
    ]


def test_stream_table_with_nulls_and_json(load):
    rows = load(rows_to_arrow(DeltaMessage("", DELTA_MULTI_VALUE).rows()))
    assert json.loads(rows[0]["value"]) == {"latitude": 51.5, "longitude": -0.1}
    assert rows[1]["value"] is None
    assert rows[0]["source"] == "derived-data"


def test_empty_table(load):
    assert load(HistoryResult({"values": [], "data": []}).to_arrow()) == []


def test_table_can_be_loaded_twice(load):
    table = HistoryResult(NARROW_RESULT).to_arrow()
    assert load(table) == load(table)
