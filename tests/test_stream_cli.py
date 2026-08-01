"""Tests for stream/cli.py using Click's test runner and a mocked WebSocket."""

import json

import pytest
from click.testing import CliRunner

from signalk_cli.stream.cli import cli
from tests.conftest import (
    DELTA_MULTI_SOURCE,
    DELTA_SINGLE_VALUE,
    DELTA_WITH_META,
    HELLO_MESSAGE,
    make_ws,
)

HOST = "--host=testserver"


@pytest.fixture
def runner():
    return CliRunner()


def _mock_open_stream(mocker, ws):
    return mocker.patch("signalk_cli.stream.cli.open_stream", return_value=ws)


# ---------------------------------------------------------------------------
# default behaviour: one message, then exit
# ---------------------------------------------------------------------------


def test_deltas_default_prints_one_message_and_exits(runner, mocker):
    ws = make_ws(
        [
            json.dumps(HELLO_MESSAGE),
            json.dumps(DELTA_SINGLE_VALUE),
            json.dumps(DELTA_SINGLE_VALUE),
        ]
    )
    _mock_open_stream(mocker, ws)
    result = runner.invoke(cli, ["deltas", HOST, "navigation.speedOverGround"])
    assert result.exit_code == 0
    assert result.output.count("navigation.speedOverGround") == 1
    assert "1 message(s), 1 row(s)" in result.output
    ws.close.assert_called_once()


def test_deltas_sends_explicit_subscribe_for_paths(runner, mocker):
    ws = make_ws([json.dumps(DELTA_SINGLE_VALUE)])
    _mock_open_stream(mocker, ws)
    runner.invoke(
        cli, ["deltas", HOST, "-c", "vessels.self", "navigation.speedOverGround"]
    )
    ws.send_payload.assert_called_once()
    sent = json.loads(ws.send_payload.call_args[0][0])
    assert sent == {
        "context": "vessels.self",
        "subscribe": [
            {
                "path": "navigation.speedOverGround",
                "period": 60000,
                "policy": "ideal",
            }
        ],
    }


def test_deltas_context_wildcard_subscribes_to_all_vessels(runner, mocker):
    ws = make_ws([json.dumps(DELTA_SINGLE_VALUE)])
    _mock_open_stream(mocker, ws)
    runner.invoke(
        cli, ["deltas", HOST, "-c", "vessels.*", "navigation.speedOverGround"]
    )
    sent = json.loads(ws.send_payload.call_args[0][0])
    assert sent["context"] == "vessels.*"


def test_deltas_no_paths_subscribes_to_wildcard(runner, mocker):
    ws = make_ws([json.dumps(DELTA_SINGLE_VALUE)])
    _mock_open_stream(mocker, ws)
    runner.invoke(cli, ["deltas", HOST])
    sent = json.loads(ws.send_payload.call_args[0][0])
    assert sent["subscribe"] == [{"path": "*", "period": 60000, "policy": "ideal"}]


def test_deltas_sends_wildcard_paths_unchanged(runner, mocker):
    ws = make_ws([json.dumps(DELTA_SINGLE_VALUE)])
    _mock_open_stream(mocker, ws)
    runner.invoke(
        cli,
        [
            "deltas",
            HOST,
            "navigation.*",
            "propulsion.*.oilTemperature",
        ],
    )
    sent = json.loads(ws.send_payload.call_args[0][0])
    assert [entry["path"] for entry in sent["subscribe"]] == [
        "navigation.*",
        "propulsion.*.oilTemperature",
    ]


# ---------------------------------------------------------------------------
# --subscribe (connection-level)
# ---------------------------------------------------------------------------


def test_subscribe_defaults_to_none(runner, mocker):
    ws = make_ws([json.dumps(DELTA_SINGLE_VALUE)])
    mock_open = _mock_open_stream(mocker, ws)
    runner.invoke(cli, ["deltas", HOST, "navigation.speedOverGround"])
    assert mock_open.call_args[0][1] == "none"


def test_subscribe_defaults_to_none_without_paths_too(runner, mocker):
    ws = make_ws([json.dumps(DELTA_SINGLE_VALUE)])
    mock_open = _mock_open_stream(mocker, ws)
    runner.invoke(cli, ["deltas", HOST])
    assert mock_open.call_args[0][1] == "none"


def test_subscribe_explicit_overrides_default(runner, mocker):
    ws = make_ws([json.dumps(DELTA_SINGLE_VALUE)])
    mock_open = _mock_open_stream(mocker, ws)
    runner.invoke(
        cli, ["deltas", HOST, "--subscribe=all", "navigation.speedOverGround"]
    )
    assert mock_open.call_args[0][1] == "all"


# ---------------------------------------------------------------------------
# --policy / --period / --min-period
# ---------------------------------------------------------------------------


def test_deltas_policy_period_defaults(runner, mocker):
    ws = make_ws([json.dumps(DELTA_SINGLE_VALUE)])
    _mock_open_stream(mocker, ws)
    runner.invoke(cli, ["deltas", HOST, "nav.sog"])
    sent = json.loads(ws.send_payload.call_args[0][0])
    entry = sent["subscribe"][0]
    assert entry["policy"] == "ideal"
    assert entry["period"] == 60000
    assert "format" not in entry
    assert "minPeriod" not in entry


def test_deltas_custom_policy_period(runner, mocker):
    ws = make_ws([json.dumps(DELTA_SINGLE_VALUE)])
    _mock_open_stream(mocker, ws)
    runner.invoke(
        cli,
        [
            "deltas",
            HOST,
            "--policy=instant",
            "--period=5",
            "--min-period=0.2",
            "nav.sog",
        ],
    )
    sent = json.loads(ws.send_payload.call_args[0][0])
    entry = sent["subscribe"][0]
    assert entry["policy"] == "instant"
    assert entry["period"] == 5000
    assert entry["minPeriod"] == 200


# ---------------------------------------------------------------------------
# --follow / --count
# ---------------------------------------------------------------------------


def test_deltas_follow_with_count_reads_multiple_messages(runner, mocker):
    ws = make_ws([json.dumps(DELTA_SINGLE_VALUE) for _ in range(3)])
    _mock_open_stream(mocker, ws)
    result = runner.invoke(cli, ["deltas", HOST, "--follow", "--count=3", "nav.sog"])
    assert result.exit_code == 0
    assert "3 message(s), 3 row(s)" in result.output


def test_deltas_count_without_follow(runner, mocker):
    ws = make_ws([json.dumps(DELTA_SINGLE_VALUE) for _ in range(2)])
    _mock_open_stream(mocker, ws)
    result = runner.invoke(cli, ["deltas", HOST, "--count=2", "nav.sog"])
    assert "2 message(s), 2 row(s)" in result.output


# ---------------------------------------------------------------------------
# --format
# ---------------------------------------------------------------------------


def test_deltas_format_json(runner, mocker):
    ws = make_ws([json.dumps(DELTA_SINGLE_VALUE)])
    _mock_open_stream(mocker, ws)
    result = runner.invoke(cli, ["deltas", HOST, "--format=json", "nav.sog"])
    assert result.exit_code == 0
    body_line = next(
        line for line in result.output.splitlines() if line.startswith("{")
    )
    row = json.loads(body_line)
    assert row["path"] == "navigation.speedOverGround"


def test_deltas_include_meta_adds_kind_column(runner, mocker):
    ws = make_ws([json.dumps(DELTA_WITH_META)])
    _mock_open_stream(mocker, ws)
    result = runner.invoke(cli, ["deltas", HOST, "--include-meta", "nav.sog"])
    assert result.exit_code == 0
    assert "kind" in result.output
    assert ",meta," in result.output
    assert "1 message(s), 2 row(s)" in result.output


def test_deltas_without_include_meta_drops_meta_rows(runner, mocker):
    ws = make_ws([json.dumps(DELTA_WITH_META)])
    _mock_open_stream(mocker, ws)
    result = runner.invoke(cli, ["deltas", HOST, "nav.sog"])
    assert result.exit_code == 0
    assert "kind" not in result.output
    assert "1 message(s), 1 row(s)" in result.output


def test_deltas_format_values(runner, mocker):
    ws = make_ws([json.dumps(DELTA_SINGLE_VALUE)])
    _mock_open_stream(mocker, ws)
    result = runner.invoke(
        cli, ["deltas", HOST, "--format=values", "--bare", "nav.sog"]
    )
    assert result.exit_code == 0
    assert result.output == "1.5\n"


# ---------------------------------------------------------------------------
# --source
# ---------------------------------------------------------------------------


def test_deltas_source_filters_csv_rows(runner, mocker):
    ws = make_ws([json.dumps(DELTA_MULTI_SOURCE)])
    _mock_open_stream(mocker, ws)
    result = runner.invoke(
        cli, ["deltas", HOST, "--source=Teltonika", "--bare", "nav.sog"]
    )
    assert result.exit_code == 0
    assert "Teltonika.GP" in result.output
    assert "derived-data" not in result.output


def test_deltas_source_filters_raw_at_message_granularity(runner, mocker):
    ws = make_ws([json.dumps(DELTA_MULTI_SOURCE)])
    _mock_open_stream(mocker, ws)
    result = runner.invoke(
        cli,
        [
            "deltas",
            HOST,
            "--source=no-such-source",
            "--format=raw",
            "--bare",
            "nav.sog",
        ],
    )
    assert result.exit_code == 0
    assert result.output == ""


def test_deltas_format_raw(runner, mocker):
    ws = make_ws([json.dumps(DELTA_SINGLE_VALUE)])
    _mock_open_stream(mocker, ws)
    result = runner.invoke(cli, ["deltas", HOST, "--format=raw", "--bare", "nav.sog"])
    assert result.exit_code == 0
    assert json.loads(result.output.strip()) == DELTA_SINGLE_VALUE


# ---------------------------------------------------------------------------
# --bare
# ---------------------------------------------------------------------------


def test_deltas_bare_suppresses_info_lines(runner, mocker):
    ws = make_ws([json.dumps(DELTA_SINGLE_VALUE)])
    _mock_open_stream(mocker, ws)
    result = runner.invoke(cli, ["deltas", HOST, "--bare", "nav.sog"])
    assert "Server:" not in result.output
    assert "message(s)" not in result.output


# ---------------------------------------------------------------------------
# connection errors
# ---------------------------------------------------------------------------


def test_deltas_connection_error(runner, mocker):
    import niquests

    mocker.patch(
        "signalk_cli.stream.cli.open_stream",
        side_effect=niquests.RequestException("connection refused"),
    )
    result = runner.invoke(cli, ["deltas", HOST, "nav.sog"])
    assert result.exit_code == 1
    assert "Error connecting to stream" in result.output


# ---------------------------------------------------------------------------
# --output / feather
# ---------------------------------------------------------------------------


def test_deltas_writes_output_file(runner, mocker, tmp_path):
    ws = make_ws([json.dumps(DELTA_SINGLE_VALUE), json.dumps(DELTA_SINGLE_VALUE)])
    _mock_open_stream(mocker, ws)
    out_file = tmp_path / "out.csv"
    result = runner.invoke(
        cli, ["deltas", HOST, "--count=2", f"--output={out_file}", "nav.sog"]
    )
    assert result.exit_code == 0
    assert f"Wrote {out_file}" in result.output
    content = out_file.read_text()
    assert "timestamp,context,source,path,value" in content
    assert content.count("navigation.speedOverGround") == 2


def test_deltas_output_extension_infers_json_format(runner, mocker, tmp_path):
    ws = make_ws([json.dumps(DELTA_SINGLE_VALUE)])
    _mock_open_stream(mocker, ws)
    out_file = tmp_path / "out.json"
    result = runner.invoke(cli, ["deltas", HOST, f"--output={out_file}", "nav.sog"])
    assert result.exit_code == 0
    row = json.loads(out_file.read_text().splitlines()[0])
    assert row["path"] == "navigation.speedOverGround"


def test_deltas_feather_stdout_error(runner, mocker):
    mock_open = _mock_open_stream(mocker, make_ws([]))
    result = runner.invoke(cli, ["deltas", HOST, "--format=feather", "nav.sog"])
    assert result.exit_code != 0
    assert "feather" in result.output.lower()
    mock_open.assert_not_called()
