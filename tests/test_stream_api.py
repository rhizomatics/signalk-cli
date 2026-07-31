"""Tests for stream_api.py — WebSocket delta client."""

import json

from signalk_cli.stream.stream_api import (
    build_subscribe_message,
    iter_deltas,
    open_stream,
    to_ws_url,
)
from tests.conftest import DELTA_MULTI_VALUE, DELTA_SINGLE_VALUE, HELLO_MESSAGE, make_ws

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
# iter_deltas
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
# open_stream
# ---------------------------------------------------------------------------


def test_open_stream_calls_ws_url_with_subscribe_param(mocker):
    mock_get = mocker.patch("signalk_cli.stream.stream_api.niquests.get")
    mock_resp = mock_get.return_value
    mock_resp.extension = "the-extension"

    result = open_stream("http://10.0.0.1", "self")

    mock_get.assert_called_once_with(
        "ws://10.0.0.1/signalk/v1/stream", params={"subscribe": "self"}, timeout=30
    )
    mock_resp.raise_for_status.assert_called_once()
    assert result == "the-extension"
