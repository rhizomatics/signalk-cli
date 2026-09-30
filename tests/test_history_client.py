"""Tests for history/api.py — HistoryClient, HistoryResult and path helpers."""

import logging
from typing import cast
from unittest.mock import MagicMock

import niquests
import pytest

from signalk_cli.history import (
    ArrowTable,
    HistoryClient,
    HistoryResult,
    SignalKError,
    TimeRange,
    build_path_specs,
    match_paths,
)
from tests.conftest import (
    CARDINALITY_NARROW_RESULT,
    NARROW_RESULT,
    POSITION_WIDE_RESULT,
    WIDE_RESULT,
    make_response,
)

HOST = "http://boat:3000"
BASE = HOST + "/signalk/v2/api/history"
HOUR = TimeRange("2026-05-27T10:00:00Z", "2026-05-27T11:00:00Z")
SERVER_PATHS = [
    "navigation.speedOverGround",
    "navigation.courseOverGroundTrue",
    "environment.wind.speedApparent",
]


class FakeSession:
    """Answers GETs from a {endpoint: payload} map and records each request."""

    def __init__(self, routes: dict[str, object]) -> None:
        self.routes = routes
        self.requests: list[tuple[str, dict]] = []
        self.closed = False

    def get(self, url, params=None, **kwargs):
        endpoint = url.removeprefix(BASE + "/")
        self.requests.append((endpoint, dict(params or {})))
        payload = self.routes.get(endpoint)
        if isinstance(payload, Exception):
            raise payload
        if payload is None:
            raise AssertionError(f"Unexpected request: {endpoint}")
        return make_response(payload)

    def close(self):
        self.closed = True

    def endpoints(self) -> list[str]:
        return [e for e, _ in self.requests]

    def params(self, endpoint: str) -> dict:
        return next(p for e, p in self.requests if e == endpoint)


def _client(routes=None, **kwargs) -> tuple[HistoryClient, FakeSession]:
    session = FakeSession(routes or {})
    kwargs.setdefault("provider", "testdb")
    return HistoryClient(
        HOST, session=cast(niquests.Session, session), **kwargs
    ), session


def _http_error(status: int, body: dict) -> niquests.HTTPError:
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = body
    exc = niquests.HTTPError(f"{status} error")
    exc.response = resp
    return exc


# ---------------------------------------------------------------------------
# build_path_specs
# ---------------------------------------------------------------------------


def test_build_path_specs_wide_by_default():
    spec, wide = build_path_specs(["navigation.speedOverGround"])
    assert wide is True
    assert spec == (
        "navigation.speedOverGround:min,"
        "navigation.speedOverGround:average,"
        "navigation.speedOverGround:max"
    )


def test_build_path_specs_position_uses_mid():
    spec, wide = build_path_specs(["navigation.position", "nav.sog"])
    assert wide is True
    assert spec == "navigation.position:mid,nav.sog:min,nav.sog:average,nav.sog:max"


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        ((["nav.sog"], "average"), "nav.sog:average"),
        ((["nav.sog"], "sma", 5), "nav.sog:sma:5"),
        ((["nav.sog"], "ema", None, 0.2), "nav.sog:ema:0.2"),
        ((["nav.sog"], "sma"), "nav.sog:sma"),
        ((["nav.sog:max", "nav.cog"], "average"), "nav.sog:max,nav.cog:average"),
        ((["nav.sog:max", "nav.cog:min"],), "nav.sog:max,nav.cog:min"),
    ],
)
def test_build_path_specs_not_wide(args, expected):
    assert build_path_specs(*args) == (expected, False)


# ---------------------------------------------------------------------------
# match_paths
# ---------------------------------------------------------------------------


def test_match_paths_literals_first_then_sorted_matches():
    assert match_paths(["depth", "navigation.*"], SERVER_PATHS) == [
        "depth",
        "navigation.courseOverGroundTrue",
        "navigation.speedOverGround",
    ]


def test_match_paths_glob_star_matches_all():
    assert match_paths(["*"], SERVER_PATHS) == sorted(SERVER_PATHS)


def test_match_paths_regex():
    assert match_paths([r"speed(Over|Apparent)"], SERVER_PATHS) == [
        "environment.wind.speedApparent",
        "navigation.speedOverGround",
    ]


def test_match_paths_invalid_regex_falls_back_to_glob(caplog):
    caplog.set_level(logging.INFO, logger="signalk_cli")
    assert match_paths(["*.speed*"], SERVER_PATHS) == [
        "environment.wind.speedApparent",
        "navigation.speedOverGround",
    ]
    assert "not valid regex, treating as glob" in caplog.text


def test_match_paths_no_match_warns(caplog):
    assert match_paths(["nonexistent.*"], SERVER_PATHS) == []
    assert "'nonexistent.*' matched no paths" in caplog.text


def test_match_paths_inline_spec_is_literal():
    assert match_paths(["navigation.speedOverGround:sma:5"], []) == [
        "navigation.speedOverGround:sma:5"
    ]


# ---------------------------------------------------------------------------
# Client basics
# ---------------------------------------------------------------------------


def test_host_is_normalised():
    client, _ = _client()
    assert HistoryClient("boat:3000/", session=MagicMock()).host == "http://boat:3000"
    assert client.base_url == BASE


def test_fetch_wraps_http_errors_with_server_message():
    client, _ = _client({"paths": _http_error(400, {"message": "bad from"})})
    with pytest.raises(SignalKError, match="bad from") as info:
        client.paths(HOUR)
    assert info.value.status_code == 400


def test_fetch_wraps_connection_errors():
    client, _ = _client({"contexts": niquests.ConnectionError("refused")})
    with pytest.raises(SignalKError, match="refused") as info:
        client.contexts(HOUR)
    assert info.value.status_code is None


def test_context_manager_closes_owned_session(mocker):
    session = MagicMock()
    mocker.patch("signalk_cli.history.api.niquests.Session", return_value=session)
    with HistoryClient(HOST):
        pass
    session.close.assert_called_once()


def test_context_manager_leaves_injected_session_open():
    client, session = _client()
    with client:
        pass
    assert session.closed is False


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------


def test_providers_and_default():
    client, _ = _client(
        {
            "_providers": {"a": {"isDefault": True}, "b": {"isDefault": False}},
            "_providers/_default": {"id": "a"},
        }
    )
    assert client.providers() == {"a": {"isDefault": True}, "b": {"isDefault": False}}
    assert client.default_provider() == "a"


def test_explicit_provider_needs_no_request():
    client, session = _client()
    assert client.provider == "testdb"
    assert session.requests == []


def test_default_provider_fetched_once():
    client, session = _client({"_providers/_default": {"id": "parquet"}}, provider=None)
    assert client.provider == "parquet"
    assert client.provider == "parquet"
    assert session.endpoints() == ["_providers/_default"]


def test_default_provider_failure_warns_and_omits_provider(caplog):
    client, session = _client(
        {
            "_providers/_default": _http_error(404, {"error": "no providers"}),
            "paths": SERVER_PATHS,
        },
        provider=None,
    )
    client.paths(HOUR)
    assert "could not fetch default provider: no providers" in caplog.text
    assert "provider" not in session.params("paths")


def test_provider_cache_written_and_read(tmp_path, monkeypatch):
    monkeypatch.setattr("signalk_cli.history.api.CACHE_DIR", tmp_path)
    first, _ = _client(
        {"_providers/_default": {"id": "parquet"}}, provider=None, cache=True
    )
    assert first.provider == "parquet"
    assert (tmp_path / "http___boat_3000.provider").read_text() == "parquet"

    second, session = _client(provider=None, cache=True)
    assert second.provider == "parquet"
    assert session.requests == []


def test_provider_cache_off_by_default(tmp_path, monkeypatch):
    monkeypatch.setattr("signalk_cli.history.api.CACHE_DIR", tmp_path)
    client, _ = _client({"_providers/_default": {"id": "parquet"}}, provider=None)
    assert client.provider == "parquet"
    assert list(tmp_path.iterdir()) == []


def test_provider_cache_unwritable_is_ignored(tmp_path, monkeypatch):
    blocker = tmp_path / "file"
    blocker.write_text("")
    monkeypatch.setattr("signalk_cli.history.api.CACHE_DIR", blocker / "sub")
    client, _ = _client(
        {"_providers/_default": {"id": "parquet"}}, provider=None, cache=True
    )
    assert client.provider == "parquet"


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def test_paths_sorted_with_time_and_provider():
    client, session = _client({"paths": SERVER_PATHS})
    assert client.paths(HOUR) == sorted(SERVER_PATHS)
    assert session.params("paths") == {
        "from": "2026-05-27T10:00:00Z",
        "to": "2026-05-27T11:00:00Z",
        "provider": "testdb",
    }


def test_contexts_sorted():
    client, _ = _client({"contexts": ["vessels.b", "vessels.a"]})
    assert client.contexts(HOUR) == ["vessels.a", "vessels.b"]


def test_default_time_is_last_hour():
    client, session = _client({"paths": []})
    client.paths()
    params = session.params("paths")
    assert set(params) == {"from", "to", "provider"}


@pytest.mark.parametrize(
    "path",
    ["depth", "navigation.speedOverGround", "navigation.speedOverGround:sma:5"],
)
def test_expand_paths_literals_need_no_request(path):
    client, session = _client()
    assert client.expand_paths([path]) == [path]
    assert session.requests == []


@pytest.mark.parametrize(
    ("pattern", "expected"),
    [
        (
            "navigation.*",
            ["navigation.courseOverGroundTrue", "navigation.speedOverGround"],
        ),
        (r"navigation\.speed", ["navigation.speedOverGround"]),
        ("*.speed?pparent", ["environment.wind.speedApparent"]),
        (
            "(course|wind)",
            ["environment.wind.speedApparent", "navigation.courseOverGroundTrue"],
        ),
        ("speedOverGround$", ["navigation.speedOverGround"]),
    ],
)
def test_expand_paths_pattern_characters(pattern, expected):
    client, _ = _client({"paths": SERVER_PATHS})
    assert client.expand_paths([pattern], HOUR) == expected


def test_expand_paths_patterns_fetch_paths_once():
    client, session = _client({"paths": SERVER_PATHS})
    assert client.expand_paths(["navigation.*", "*.wind.*"], HOUR) == [
        "environment.wind.speedApparent",
        "navigation.courseOverGroundTrue",
        "navigation.speedOverGround",
    ]
    assert session.endpoints() == ["paths"]


def test_request_params_drops_none_extras():
    client, _ = _client()
    assert client.request_params(HOUR, resolution=None, context="vessels.x") == {
        "from": "2026-05-27T10:00:00Z",
        "to": "2026-05-27T11:00:00Z",
        "provider": "testdb",
        "context": "vessels.x",
    }


# ---------------------------------------------------------------------------
# Values
# ---------------------------------------------------------------------------


def test_value_params():
    client, _ = _client(context="vessels.other")
    params, wide = client.value_params(
        ["nav.sog"], HOUR, aggregation="sma", samples=3, resolution="1m"
    )
    assert wide is False
    assert params == {
        "from": "2026-05-27T10:00:00Z",
        "to": "2026-05-27T11:00:00Z",
        "provider": "testdb",
        "paths": "nav.sog:sma:3",
        "context": "vessels.other",
        "resolution": "1m",
    }


def test_value_params_context_override():
    client, _ = _client()
    params, _ = client.value_params(["nav.sog"], HOUR, context="vessels.x")
    assert params["context"] == "vessels.x"


def test_value_params_date_duration_expanded():
    client, _ = _client()
    params, _ = client.value_params(
        ["nav.sog"], TimeRange(start="2026-05-27T00:00:00Z", duration="P1D")
    )
    assert (params["from"], params["to"]) == (
        "2026-05-27T00:00:00Z",
        "2026-05-28T00:00:00Z",
    )
    assert "duration" not in params


def test_value_params_nothing_matched():
    client, _ = _client({"paths": SERVER_PATHS})
    with pytest.raises(ValueError, match="No paths"):
        client.value_params(["nothing.*"], HOUR)


def test_values_expands_patterns_then_fetches():
    client, session = _client({"paths": SERVER_PATHS, "values": WIDE_RESULT})
    result = client.values(["navigation.speed*"], HOUR)
    assert isinstance(result, HistoryResult)
    assert result.wide is True
    assert result.payload == WIDE_RESULT
    assert session.endpoints() == ["paths", "values"]
    assert session.params("values")["paths"].startswith(
        "navigation.speedOverGround:min"
    )


def test_values_expand_false_sends_patterns_as_given():
    client, session = _client({"values": NARROW_RESULT})
    client.values(["nav.*:max"], HOUR, expand=False)
    assert session.params("values")["paths"] == "nav.*:max"


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------


def _pa():
    return pytest.importorskip("pyarrow")


def test_query_wide_table():
    pa = _pa()
    client, _ = _client({"values": WIDE_RESULT})
    table = client.query(["nav.sog"], HOUR)
    assert isinstance(table, ArrowTable)
    t = pa.table(table)
    assert t.column_names == [
        "timestamp",
        "path",
        "min_value",
        "avg_value",
        "max_value",
    ]
    assert t.schema.field("timestamp").type == pa.timestamp("us", tz="UTC")
    assert t.column("avg_value").to_pylist() == [2.0, 1.5]


def test_query_long_table_when_aggregated():
    pa = _pa()
    client, _ = _client({"values": NARROW_RESULT})
    t = pa.table(client.query(["nav.sog"], HOUR, aggregation="average"))
    assert t.column_names == ["timestamp", "path", "value"]
    assert t.schema.field("value").type == pa.float64()
    assert t.column("value").to_pylist() == [1.5, 2.0]


def test_query_shape_override():
    client, _ = _client({"values": WIDE_RESULT})
    table = client.query(["nav.sog"], HOUR, shape="long")
    assert table.column_names == ["timestamp", "path", "value"]
    assert table.num_rows == 6


def test_query_position_wide_columns():
    pa = _pa()
    client, _ = _client({"values": POSITION_WIDE_RESULT})
    t = pa.table(client.query(["navigation.position"], HOUR))
    assert t.column_names == ["timestamp", "path", "longitude", "latitude"]
    assert t.column("longitude").to_pylist() == [51.5, 51.6]


def test_long_table_mixed_values_become_json_text():
    pa = _pa()
    result = HistoryResult(
        {
            "values": [{"path": "nav.sog"}, {"path": "navigation.position"}],
            "data": [["2026-05-27T10:00:00Z", 1.5, {"latitude": 1, "longitude": 2}]],
        }
    )
    t = pa.table(result.to_arrow())
    assert t.schema.field("value").type == pa.string()
    assert t.column("value").to_pylist() == ["1.5", '{"latitude": 1, "longitude": 2}']


def test_empty_result_keeps_schema():
    pa = _pa()
    t = pa.table(HistoryResult({"values": [], "data": []}).to_arrow())
    assert t.num_rows == 0
    assert t.schema.field("path").type == pa.string()


def test_result_paths():
    assert HistoryResult(WIDE_RESULT).paths == ["navigation.speedOverGround"]


def test_cardinality_table():
    pa = _pa()
    client, session = _client({"values": CARDINALITY_NARROW_RESULT})
    t = pa.table(
        client.cardinality(["navigation.speedOverGround"], HOUR, resolution=60)
    )
    assert t.column_names == [
        "path",
        "distinct_values",
        "distinct_values_2_decimal_places",
        "nulls",
        "zeroes",
        "min",
        "max",
        "average",
    ]
    row = t.to_pylist()[0]
    assert row["nulls"] == 1
    assert row["max"] == 2.0
    assert t.schema.field("nulls").type == pa.int64()
    assert session.params("values")["paths"] == "navigation.speedOverGround"
    assert session.params("values")["resolution"] == 60


def test_cardinality_nothing_matched():
    client, _ = _client({"paths": []})
    with pytest.raises(ValueError, match="No paths"):
        client.cardinality_rows(["*"], HOUR)
