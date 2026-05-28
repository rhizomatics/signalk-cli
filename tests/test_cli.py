"""Tests for CLI commands using Click's test runner and mocked HTTP."""

import pytest
from click.testing import CliRunner

from signalk_cli.history.cli import cli
from tests.conftest import NARROW_RESULT, WIDE_RESULT, make_response

HOST = "--host=testserver"
PROVIDER = "--provider=testdb"
DURATION = "--duration=PT1H"
BASE_ARGS = [HOST, PROVIDER, DURATION]


@pytest.fixture
def runner():
    return CliRunner()


# ---------------------------------------------------------------------------
# _build_path_specs (pure unit — no HTTP)
# ---------------------------------------------------------------------------


def test_build_path_specs_wide_mode():
    from signalk_cli.history.cli import _build_path_specs

    query, wide = _build_path_specs(["navigation.speedOverGround"], None, None, None)
    assert wide is True
    assert "navigation.speedOverGround:min" in query
    assert "navigation.speedOverGround:average" in query
    assert "navigation.speedOverGround:max" in query


def test_build_path_specs_aggregation():
    from signalk_cli.history.cli import _build_path_specs

    query, wide = _build_path_specs(["nav.sog"], "average", None, None)
    assert wide is False
    assert query == "nav.sog:average"


def test_build_path_specs_sma_with_samples():
    from signalk_cli.history.cli import _build_path_specs

    query, wide = _build_path_specs(["nav.sog"], "sma", 5, None)
    assert query == "nav.sog:sma:5"


def test_build_path_specs_ema_with_alpha():
    from signalk_cli.history.cli import _build_path_specs

    query, wide = _build_path_specs(["nav.sog"], "ema", None, 0.2)
    assert query == "nav.sog:ema:0.2"


def test_build_path_specs_inline_passthrough():
    from signalk_cli.history.cli import _build_path_specs

    query, wide = _build_path_specs(["nav.sog:max"], None, None, None)
    assert wide is False
    assert query == "nav.sog:max"


def test_build_path_specs_inline_survives_agg():
    from signalk_cli.history.cli import _build_path_specs

    query, wide = _build_path_specs(["nav.sog:max", "nav.cog"], "average", None, None)
    assert "nav.sog:max" in query
    assert "nav.cog:average" in query


# ---------------------------------------------------------------------------
# query command
# ---------------------------------------------------------------------------


def _mock_values(mocker, values_result):
    """Patch only the /values HTTP call. Use dot-free path args to skip expansion."""
    mocker.patch(
        "signalk_cli.history.cli.niquests.get",
        return_value=make_response(values_result),
    )


# Use "sog" (no dots, no colon) so expand_paths treats it as a literal
# and never calls the /paths endpoint — keeping the test self-contained.
LITERAL_PATH = "sog"


def test_query_wide_mode_csv_stdout(runner, mocker):
    _mock_values(mocker, WIDE_RESULT)
    result = runner.invoke(cli, ["query", *BASE_ARGS, "--stdout", LITERAL_PATH])
    assert result.exit_code == 0
    assert "min_value,avg_value,max_value" in result.output
    assert "2026-05-27T10:00:00Z" in result.output


def test_query_narrow_mode_csv_stdout(runner, mocker):
    _mock_values(mocker, NARROW_RESULT)
    result = runner.invoke(
        cli, ["query", *BASE_ARGS, "--agg=average", "--stdout", LITERAL_PATH]
    )
    assert result.exit_code == 0
    assert "timestamp,path,value" in result.output


def test_query_no_header(runner, mocker):
    _mock_values(mocker, NARROW_RESULT)
    result = runner.invoke(
        cli,
        ["query", *BASE_ARGS, "--agg=average", "--no-header", "--stdout", LITERAL_PATH],
    )
    assert result.exit_code == 0
    assert "timestamp" not in result.output


def test_query_feather_stdout_error(runner, mocker):
    mocker.patch("signalk_cli.history.cli.niquests.get", return_value=make_response({}))
    result = runner.invoke(
        cli,
        ["query", *BASE_ARGS, "--format=feather", "--stdout", "nav.sog"],
    )
    assert result.exit_code != 0
    assert "not supported" in result.output.lower() or "not supported" in (
        result.exception and str(result.exception) or ""
    )


def test_query_http_error(runner, mocker):
    import niquests

    mock_resp = make_response({"error": "bad request"}, status_code=400)
    mock_resp.raise_for_status.side_effect = niquests.HTTPError(response=mock_resp)
    mocker.patch("signalk_cli.history.cli.niquests.get", return_value=mock_resp)
    result = runner.invoke(
        cli,
        ["query", *BASE_ARGS, "--agg=average", "nav.sog"],
    )
    assert result.exit_code == 1


def test_query_bare_mode_csv_stdout(runner, mocker):
    _mock_values(mocker, WIDE_RESULT)
    result = runner.invoke(cli, ["query", *BASE_ARGS, "--bare", LITERAL_PATH])
    assert result.exit_code == 0
    assert "min_value,avg_value,max_value" in result.output
    # No informational lines on stdout
    assert "Server:" not in result.output
    assert "Provider:" not in result.output


def test_query_bare_mode_no_info_on_stderr(runner, mocker):
    _mock_values(mocker, WIDE_RESULT)
    result = runner.invoke(cli, ["query", *BASE_ARGS, "--bare", LITERAL_PATH])
    assert result.exit_code == 0
    # Click's test runner captures mixed output; verify no info noise at all
    assert "Format:" not in result.output
    assert "Aggregation:" not in result.output


def test_query_writes_file(runner, mocker, tmp_path):
    _mock_values(mocker, NARROW_RESULT)
    out_file = tmp_path / "out.csv"
    result = runner.invoke(
        cli,
        ["query", *BASE_ARGS, "--agg=average", f"--output={out_file}", LITERAL_PATH],
    )
    assert result.exit_code == 0
    content = out_file.read_text()
    assert "timestamp,path,value" in content


# ---------------------------------------------------------------------------
# list-paths
# ---------------------------------------------------------------------------


def test_list_paths_bare(runner, mocker, server_paths):
    mocker.patch(
        "signalk_cli.history.history_api.niquests.get",
        return_value=make_response(server_paths),
    )
    result = runner.invoke(cli, ["list-paths", HOST, PROVIDER, DURATION, "--bare"])
    assert result.exit_code == 0
    for path in server_paths:
        assert path in result.output
    assert "Server:" not in result.output
    assert "path(s)" not in result.output


def test_list_paths(runner, mocker, server_paths):
    mocker.patch(
        "signalk_cli.history.history_api.niquests.get",
        return_value=make_response(server_paths),
    )
    result = runner.invoke(cli, ["list-paths", HOST, PROVIDER, DURATION])
    assert result.exit_code == 0
    for path in server_paths:
        assert path in result.output


def test_list_paths_count(runner, mocker, server_paths):
    mocker.patch(
        "signalk_cli.history.history_api.niquests.get",
        return_value=make_response(server_paths),
    )
    result = runner.invoke(cli, ["list-paths", HOST, PROVIDER, DURATION])
    assert f"{len(server_paths)} path(s)" in result.output


# ---------------------------------------------------------------------------
# list-providers
# ---------------------------------------------------------------------------


def test_list_providers_bare(runner, mocker):
    providers = {
        "signalk-parquet": {"isDefault": True},
        "influxdb": {"isDefault": False},
    }
    mocker.patch(
        "signalk_cli.history.cli.niquests.get",
        return_value=make_response(providers),
    )
    result = runner.invoke(cli, ["list-providers", HOST, "--bare"])
    assert result.exit_code == 0
    assert "signalk-parquet (default)" in result.output
    assert "Server:" not in result.output
    assert "provider(s)" not in result.output


def test_list_providers(runner, mocker):
    providers = {
        "signalk-parquet": {"isDefault": True},
        "influxdb": {"isDefault": False},
    }
    mocker.patch(
        "signalk_cli.history.cli.niquests.get",
        return_value=make_response(providers),
    )
    result = runner.invoke(cli, ["list-providers", HOST])
    assert result.exit_code == 0
    assert "signalk-parquet (default)" in result.output
    assert "influxdb" in result.output
    assert "2 provider(s)" in result.output


# ---------------------------------------------------------------------------
# list-contexts
# ---------------------------------------------------------------------------


def test_list_contexts_bare(runner, mocker):
    contexts = ["vessels.self", "vessels.urn:mrn:imo:mmsi:123456789"]
    mocker.patch(
        "signalk_cli.history.cli.niquests.get",
        return_value=make_response(contexts),
    )
    result = runner.invoke(cli, ["list-contexts", HOST, PROVIDER, DURATION, "--bare"])
    assert result.exit_code == 0
    for ctx in contexts:
        assert ctx in result.output
    assert "Server:" not in result.output
    assert "context(s)" not in result.output


def test_list_contexts(runner, mocker):
    contexts = ["vessels.self", "vessels.urn:mrn:imo:mmsi:123456789"]
    mocker.patch(
        "signalk_cli.history.cli.niquests.get",
        return_value=make_response(contexts),
    )
    result = runner.invoke(cli, ["list-contexts", HOST, PROVIDER, DURATION])
    assert result.exit_code == 0
    for ctx in contexts:
        assert ctx in result.output
    assert "2 context(s)" in result.output
