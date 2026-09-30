"""Tests for stream/api.py — StreamClient, DeltaStream, DeltaMessage and helpers."""

import json
from typing import cast
from unittest.mock import MagicMock

import niquests
import pytest

from signalk_cli.stream import (
    ArrowTable,
    DeltaMessage,
    DeltaRow,
    DeltaStream,
    SignalKError,
    StreamClient,
    build_subscribe_message,
    rows_to_arrow,
    source_matches,
    to_ws_url,
)
from tests.conftest import (
    DELTA_MULTI_SOURCE,
    DELTA_MULTI_VALUE,
    DELTA_SINGLE_VALUE,
    DELTA_WITH_META,
    HELLO_MESSAGE,
    make_ws,
)


def _msg(payload: dict) -> DeltaMessage:
    return DeltaMessage(json.dumps(payload), payload)


def iter_deltas(ws, count=None):
    return [(m.text, m.payload) for m in DeltaStream(ws).messages(count)]


# ---------------------------------------------------------------------------
# to_ws_url
# ---------------------------------------------------------------------------


def test_to_ws_url_http_to_ws():
    assert to_ws_url("http://10.0.0.1") == "ws://10.0.0.1/signalk/v1/stream"


def test_to_ws_url_https_to_wss():
    assert (
        to_ws_url("https://boat.example.com")
        == "wss://boat.example.com/signalk/v1/stream"
    )


def test_to_ws_url_ignores_path_and_trailing_slash():
    assert to_ws_url("http://10.0.0.1:3000/") == "ws://10.0.0.1:3000/signalk/v1/stream"


# ---------------------------------------------------------------------------
# build_subscribe_message
# ---------------------------------------------------------------------------


def test_build_subscribe_message_with_paths():
    msg = build_subscribe_message(
        "vessels.self", ["navigation.speedOverGround", "environment.*"]
    )
    assert msg == {
        "context": "vessels.self",
        "subscribe": [
            {"path": "navigation.speedOverGround"},
            {"path": "environment.*"},
        ],
    }


def test_build_subscribe_message_end_of_path_wildcard():
    """A trailing '*' matches any suffix (SignalK Subscription Protocol)."""
    msg = build_subscribe_message("vessels.self", ["navigation.*"])
    assert msg["subscribe"] == [{"path": "navigation.*"}]


def test_build_subscribe_message_mid_path_wildcard():
    """A '*' as a middle segment matches any single segment there."""
    msg = build_subscribe_message("vessels.self", ["propulsion.*.oilTemperature"])
    assert msg["subscribe"] == [{"path": "propulsion.*.oilTemperature"}]


def test_build_subscribe_message_explicit_bare_wildcard():
    msg = build_subscribe_message("vessels.self", ["*"])
    assert msg == {"context": "vessels.self", "subscribe": [{"path": "*"}]}


def test_build_subscribe_message_no_paths_defaults_to_wildcard():
    msg = build_subscribe_message("vessels.self", [])
    assert msg == {"context": "vessels.self", "subscribe": [{"path": "*"}]}


def test_build_subscribe_message_with_period_and_policy():
    msg = build_subscribe_message(
        "vessels.self",
        ["navigation.speedOverGround"],
        period_ms=60000,
        policy="ideal",
    )
    assert msg["subscribe"] == [
        {
            "path": "navigation.speedOverGround",
            "period": 60000,
            "policy": "ideal",
        }
    ]


def test_build_subscribe_message_min_period_only_when_given():
    msg = build_subscribe_message(
        "vessels.self", ["nav.sog"], policy="instant", min_period_ms=200
    )
    assert msg["subscribe"] == [
        {"path": "nav.sog", "policy": "instant", "minPeriod": 200}
    ]


def test_build_subscribe_message_extras_applied_to_every_path():
    msg = build_subscribe_message(
        "vessels.self", ["nav.sog", "nav.cog"], period_ms=5000
    )
    assert msg["subscribe"] == [
        {"path": "nav.sog", "period": 5000},
        {"path": "nav.cog", "period": 5000},
    ]


def test_build_subscribe_message_no_extras_omits_fields():
    msg = build_subscribe_message("vessels.self", ["nav.sog"])
    assert msg["subscribe"] == [{"path": "nav.sog"}]


# ---------------------------------------------------------------------------
# DeltaStream.messages
# ---------------------------------------------------------------------------


def test_iter_deltas_skips_hello_message():
    ws = make_ws([json.dumps(HELLO_MESSAGE), json.dumps(DELTA_SINGLE_VALUE), None])
    results = list(iter_deltas(ws))
    assert len(results) == 1
    raw, parsed = results[0]
    assert parsed == DELTA_SINGLE_VALUE
    assert json.loads(raw) == DELTA_SINGLE_VALUE


def test_iter_deltas_stops_on_none():
    ws = make_ws([json.dumps(DELTA_SINGLE_VALUE), None, json.dumps(DELTA_MULTI_VALUE)])
    results = list(iter_deltas(ws))
    assert len(results) == 1


def test_iter_deltas_respects_count():
    ws = make_ws(
        [
            json.dumps(DELTA_SINGLE_VALUE),
            json.dumps(DELTA_SINGLE_VALUE),
            json.dumps(DELTA_SINGLE_VALUE),
        ]
    )
    results = list(iter_deltas(ws, count=2))
    assert len(results) == 2


def test_iter_deltas_skips_invalid_json():
    ws = make_ws(["not json", json.dumps(DELTA_SINGLE_VALUE), None])
    results = list(iter_deltas(ws))
    assert len(results) == 1


def test_iter_deltas_decodes_bytes_payload():
    ws = make_ws([json.dumps(DELTA_SINGLE_VALUE).encode(), None])
    results = list(iter_deltas(ws))
    assert len(results) == 1
    assert results[0][1] == DELTA_SINGLE_VALUE


# ---------------------------------------------------------------------------
# DeltaMessage.rows
# ---------------------------------------------------------------------------


def test_rows_single_value():
    rows = _msg(DELTA_SINGLE_VALUE).rows()
    assert rows == [
        (
            "2026-07-31T15:38:08.041Z",
            "vessels.urn:mrn:imo:mmsi:235094115",
            "Teltonika.GP",
            "navigation.speedOverGround",
            "value",
            1.5,
        )
    ]


def test_rows_multi_value_dict_and_none():
    rows = _msg(DELTA_MULTI_VALUE).rows()
    assert len(rows) == 2
    assert rows[0].context == "vessels.self"
    assert rows[0].source == "derived-data"
    assert rows[0].path == "navigation.position"
    assert rows[0].value == {"latitude": 51.5, "longitude": -0.1}
    assert rows[1].path == "navigation.courseOverGroundTrue"
    assert rows[1].value is None


def test_rows_falls_back_to_source_object():
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
    rows = _msg(delta).rows()
    assert json.loads(rows[0].source) == {"label": "gps0"}


def test_rows_ignores_meta_by_default():
    rows = _msg(DELTA_WITH_META).rows()
    assert len(rows) == 1
    assert rows[0].path == "navigation.speedOverGround"
    assert rows[0].value == 2.5


def test_rows_include_meta_adds_kind_and_meta_rows():
    rows = _msg(DELTA_WITH_META).rows(include_meta=True)
    assert len(rows) == 2
    assert rows[0][3:] == ("navigation.speedOverGround", "value", 2.5)
    assert rows[1].path == "navigation.speedOverGround"
    assert rows[1].kind == "meta"
    assert rows[1].value == {"units": "m/s", "description": "Speed over ground"}


def test_rows_filters_by_source_substring():
    rows = _msg(DELTA_MULTI_SOURCE).rows(sources=("Teltonika",))
    assert len(rows) == 1
    assert rows[0].source == "Teltonika.GP"


def test_rows_filters_by_source_glob():
    rows = _msg(DELTA_MULTI_SOURCE).rows(sources=("*.GP",))
    assert len(rows) == 1
    assert rows[0].source == "Teltonika.GP"


def test_rows_multiple_source_patterns_are_ored():
    rows = _msg(DELTA_MULTI_SOURCE).rows(sources=("Teltonika", "derived-data"))
    assert len(rows) == 2


def test_rows_no_matching_source_yields_no_rows():
    rows = _msg(DELTA_MULTI_SOURCE).rows(sources=("no-such-source",))
    assert rows == []


# ---------------------------------------------------------------------------
# source_matches / DeltaMessage.matches_sources
# ---------------------------------------------------------------------------


def test_source_matches_no_patterns_matches_anything():
    assert source_matches("anything", ())


def test_source_matches_substring():
    assert source_matches("Teltonika.GP", ("Teltonika",))
    assert not source_matches("derived-data", ("Teltonika",))


def test_source_matches_glob():
    assert source_matches("Teltonika.GP", ("*.GP",))
    assert not source_matches("derived-data", ("*.GP",))


def test_matches_sources_true_if_any_update_matches():
    assert _msg(DELTA_MULTI_SOURCE).matches_sources(("derived-data",))


def test_matches_sources_false_if_no_update_matches():
    assert not _msg(DELTA_MULTI_SOURCE).matches_sources(("no-such-source",))


def test_matches_sources_empty_matches():
    assert _msg(DELTA_MULTI_SOURCE).matches_sources(())


# ---------------------------------------------------------------------------
# DeltaStream
# ---------------------------------------------------------------------------


def test_messages_skip_non_object_json():
    ws = make_ws(["[1, 2]", json.dumps(DELTA_SINGLE_VALUE), None])
    assert len(iter_deltas(ws)) == 1


def test_iterating_stream_yields_messages():
    ws = make_ws([json.dumps(DELTA_SINGLE_VALUE), None])
    messages = list(DeltaStream(ws))
    assert messages == [
        DeltaMessage(json.dumps(DELTA_SINGLE_VALUE), DELTA_SINGLE_VALUE)
    ]


def test_connection_lost_raises_signalk_error():
    ws = MagicMock()
    ws.next_payload.side_effect = niquests.ReadTimeout("read timed out")
    with pytest.raises(SignalKError, match="read timed out"):
        list(DeltaStream(ws).messages())


def test_stream_context_manager_closes_ws():
    ws = make_ws([])
    with DeltaStream(ws):
        pass
    ws.close.assert_called_once()


def test_stream_rows_across_messages_with_filters():
    ws = make_ws([json.dumps(DELTA_MULTI_SOURCE), json.dumps(DELTA_WITH_META), None])
    rows = list(DeltaStream(ws).rows(include_meta=True, sources=("derived",)))
    assert [(r.source, r.kind, r.value) for r in rows] == [
        ("derived-data", "value", 1.6),
        ("derived-data", "value", 2.5),
        ("derived-data", "meta", {"units": "m/s", "description": "Speed over ground"}),
    ]


def test_stream_collect_counts_messages():
    ws = make_ws([json.dumps(DELTA_SINGLE_VALUE)] * 3)
    table = DeltaStream(ws).collect(2)
    assert isinstance(table, ArrowTable)
    assert table.num_rows == 2


# ---------------------------------------------------------------------------
# rows_to_arrow
# ---------------------------------------------------------------------------


def test_rows_to_arrow_types():
    pa = pytest.importorskip("pyarrow")
    t = pa.table(rows_to_arrow(_msg(DELTA_SINGLE_VALUE).rows()))
    assert t.column_names == ["timestamp", "context", "source", "path", "value"]
    assert t.schema.field("timestamp").type == pa.timestamp("us", tz="UTC")
    assert t.schema.field("value").type == pa.float64()
    assert t.column("timestamp").to_pylist()[0].microsecond == 41000


def test_rows_to_arrow_include_meta_and_json_values():
    pa = pytest.importorskip("pyarrow")
    t = pa.table(
        rows_to_arrow(_msg(DELTA_WITH_META).rows(include_meta=True), include_meta=True)
    )
    assert t.column_names == ["timestamp", "context", "source", "path", "kind", "value"]
    assert t.schema.field("value").type == pa.string()
    assert t.column("value").to_pylist() == [
        "2.5",
        '{"units": "m/s", "description": "Speed over ground"}',
    ]


def test_rows_to_arrow_missing_timestamp_is_null():
    row = DeltaRow("", "vessels.self", "src", "p", "value", 1)
    assert rows_to_arrow([row]).to_pydict()["timestamp"] == [None]


def test_rows_to_arrow_empty_has_schema():
    pa = pytest.importorskip("pyarrow")
    t = pa.table(rows_to_arrow([]))
    assert t.num_rows == 0
    assert t.schema.field("path").type == pa.string()


# ---------------------------------------------------------------------------
# StreamClient
# ---------------------------------------------------------------------------


def _session(ws) -> MagicMock:
    session = MagicMock()
    session.get.return_value.extension = ws
    return session


def _client(ws, **kwargs) -> tuple[StreamClient, MagicMock]:
    session = _session(ws)
    return StreamClient(
        "boat:3000", session=cast(niquests.Session, session), **kwargs
    ), session


def test_open_connects_and_subscribes():
    ws = make_ws([])
    client, session = _client(ws, context="vessels.*", subscribe="self")
    stream = client.open(
        ["navigation.*"], policy="instant", period=None, min_period=0.5, timeout=None
    )
    assert isinstance(stream, DeltaStream)
    session.get.assert_called_once_with(
        "ws://boat:3000/signalk/v1/stream", params={"subscribe": "self"}, timeout=None
    )
    assert json.loads(ws.send_payload.call_args[0][0]) == {
        "context": "vessels.*",
        "subscribe": [{"path": "navigation.*", "policy": "instant", "minPeriod": 500}],
    }


def test_open_defaults():
    ws = make_ws([])
    client, session = _client(ws)
    client.open()
    assert session.get.call_args.kwargs == {
        "params": {"subscribe": "none"},
        "timeout": 30,
    }
    assert json.loads(ws.send_payload.call_args[0][0]) == {
        "context": "vessels.self",
        "subscribe": [{"path": "*", "period": 60000, "policy": "ideal"}],
    }


def test_open_connection_error():
    client, session = _client(make_ws([]))
    session.get.side_effect = niquests.ConnectionError("refused")
    with pytest.raises(SignalKError, match="refused"):
        client.open()


def test_open_without_websocket_extension():
    client, _ = _client(None)
    with pytest.raises(SignalKError, match="did not accept a WebSocket"):
        client.open()


def test_collect_reads_count_then_closes():
    ws = make_ws([json.dumps(HELLO_MESSAGE)] + [json.dumps(DELTA_MULTI_SOURCE)] * 3)
    client, _ = _client(ws)
    table = client.collect(
        ["navigation.speedOverGround"], count=2, sources=("Teltonika",)
    )
    assert table.num_rows == 2
    assert table.to_pydict()["source"] == ["Teltonika.GP", "Teltonika.GP"]
    ws.close.assert_called_once()


def test_client_context_manager_closes_owned_session(mocker):
    session = MagicMock()
    mocker.patch("signalk_cli.stream.api.niquests.Session", return_value=session)
    with StreamClient("boat"):
        pass
    session.close.assert_called_once()


def test_client_leaves_injected_session_open():
    client, session = _client(make_ws([]))
    with client:
        pass
    session.close.assert_not_called()
