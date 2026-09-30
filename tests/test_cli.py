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
# query command
# ---------------------------------------------------------------------------


def _mock_values(mocker, values_result):
    """Patch only the /values HTTP call. Use dot-free path args to skip expansion."""
    mocker.patch(
        "niquests.Session.get",
        return_value=make_response(values_result),
    )


# Use "sog" (no dots, no colon) so expand_paths treats it as a literal
# and never calls the /paths endpoint — keeping the test self-contained.
LITERAL_PATH = "sog"


def test_query_wide_mode_csv_stdout(runner, mocker):
    _mock_values(mocker, WIDE_RESULT)
    result = runner.invoke(cli, ["query", *BASE_ARGS, LITERAL_PATH])
    assert result.exit_code == 0
    assert "min_value,avg_value,max_value" in result.output
    assert "2026-05-27T10:00:00Z" in result.output


def test_query_narrow_mode_csv_stdout(runner, mocker):
    _mock_values(mocker, NARROW_RESULT)
    result = runner.invoke(cli, ["query", *BASE_ARGS, "--agg=average", LITERAL_PATH])
    assert result.exit_code == 0
    assert "timestamp,path,value" in result.output


def test_query_no_header(runner, mocker):
    _mock_values(mocker, NARROW_RESULT)
    result = runner.invoke(
        cli,
        ["query", *BASE_ARGS, "--agg=average", "--no-header", LITERAL_PATH],
    )
    assert result.exit_code == 0
    assert "timestamp" not in result.output


def test_query_feather_stdout_error(runner, mocker):
    mocker.patch("niquests.Session.get", return_value=make_response({}))
    result = runner.invoke(
        cli,
        ["query", *BASE_ARGS, "--format=feather", "nav.sog"],
    )
    assert result.exit_code != 0
    assert "feather" in result.output.lower()


def test_query_http_error(runner, mocker):
    import niquests

    mock_resp = make_response({"error": "bad request"}, status_code=400)
    mock_resp.raise_for_status.side_effect = niquests.HTTPError(response=mock_resp)
    mocker.patch("niquests.Session.get", return_value=mock_resp)
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
        "niquests.Session.get",
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
        "niquests.Session.get",
        return_value=make_response(server_paths),
    )
    result = runner.invoke(cli, ["list-paths", HOST, PROVIDER, DURATION])
    assert result.exit_code == 0
    for path in server_paths:
        assert path in result.output


def test_list_paths_count(runner, mocker, server_paths):
    mocker.patch(
        "niquests.Session.get",
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
        "niquests.Session.get",
        return_value=make_response(providers),
    )
    result = runner.invoke(cli, ["list-providers", HOST, "--bare"])
    assert result.exit_code == 0
    assert "provider,isDefault" in result.output
    assert "signalk-parquet,True" in result.output
    assert "Server:" not in result.output
    assert "provider(s)" not in result.output


def test_list_providers(runner, mocker):
    providers = {
        "signalk-parquet": {"isDefault": True},
        "influxdb": {"isDefault": False},
    }
    mocker.patch(
        "niquests.Session.get",
        return_value=make_response(providers),
    )
    result = runner.invoke(cli, ["list-providers", HOST])
    assert result.exit_code == 0
    assert "provider,isDefault" in result.output
    assert "signalk-parquet,True" in result.output
    assert "influxdb,False" in result.output
    assert "2 provider(s)" in result.output


# ---------------------------------------------------------------------------
# list-contexts
# ---------------------------------------------------------------------------


def test_list_contexts_bare(runner, mocker):
    contexts = ["vessels.self", "vessels.urn:mrn:imo:mmsi:123456789"]
    mocker.patch(
        "niquests.Session.get",
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
        "niquests.Session.get",
        return_value=make_response(contexts),
    )
    result = runner.invoke(cli, ["list-contexts", HOST, PROVIDER, DURATION])
    assert result.exit_code == 0
    for ctx in contexts:
        assert ctx in result.output
    assert "2 context(s)" in result.output


def test_resolve_host_without_zeroconf(monkeypatch):
    import click
    import pytest

    from signalk_cli import _cli, net

    monkeypatch.setattr(net, "Zeroconf", None)
    assert net.discover_host() is None
    assert _cli.resolve_host("boat.local") == "http://boat.local"
    with pytest.raises(click.UsageError, match="zeroconf not installed"):
        _cli.resolve_host(None, no_cache=True)
