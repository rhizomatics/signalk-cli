"""History CLI output formats, file naming and error paths, over a mocked session."""

import json

import niquests
import pytest
from click.testing import CliRunner

from signalk_cli.history.cli import cli
from tests.conftest import (
    CARDINALITY_NARROW_RESULT,
    NARROW_RESULT,
    WIDE_RESULT,
    make_response,
    url_dispatcher,
)

ARGS = ["--host=testserver", "--provider=testdb", "--duration=PT1H"]
SERVER_PATHS = ["navigation.speedOverGround", "environment.wind.speedApparent"]


@pytest.fixture
def runner():
    return CliRunner()


def _serve(mocker, routes):
    return mocker.patch("niquests.Session.get", side_effect=url_dispatcher(routes))


def _raw_response(text: str, chunks: list[str] | None = None):
    resp = make_response(json.loads(text))
    resp.text = text
    resp.__enter__.return_value = resp
    resp.iter_content.return_value = chunks or [text]
    return resp


def _http_error(message: str):
    resp = make_response({"error": message}, status_code=500)
    resp.raise_for_status.side_effect = niquests.HTTPError(response=resp)
    return resp


# ---------------------------------------------------------------------------
# query: formats
# ---------------------------------------------------------------------------


def test_query_json_wide_stdout(runner, mocker):
    _serve(mocker, {"/values": WIDE_RESULT})
    result = runner.invoke(cli, ["query", *ARGS, "--format=json", "--bare", "sog"])
    assert result.exit_code == 0
    rows = json.loads(result.output)
    assert rows[0]["avg_value"] == "2.0"


def test_query_json_long_pretty_to_file(runner, mocker, tmp_path):
    _serve(mocker, {"/values": NARROW_RESULT})
    out = tmp_path / "out.json"
    result = runner.invoke(
        cli, ["query", *ARGS, "--agg=average", "--pretty", f"--output={out}", "sog"]
    )
    assert result.exit_code == 0, result.output
    assert json.loads(out.read_text())[1]["value"] == "2.0"
    assert out.read_text().startswith("[\n  {")
    assert "2 rows, 1 unique path(s): navigation.speedOverGround" in result.output


def test_query_raw_streams_body(runner, mocker):
    body = json.dumps(NARROW_RESULT)
    get = mocker.patch(
        "niquests.Session.get", return_value=_raw_response(body, [body[:10], body[10:]])
    )
    result = runner.invoke(cli, ["query", *ARGS, "--format=raw", "--bare", "sog"])
    assert result.exit_code == 0
    assert result.output == body + "\n"
    assert get.call_args.kwargs["stream"] is True


def test_query_raw_pretty_stdout(runner, mocker):
    mocker.patch(
        "niquests.Session.get", return_value=_raw_response(json.dumps(NARROW_RESULT))
    )
    result = runner.invoke(
        cli, ["query", *ARGS, "--format=raw", "--pretty", "--bare", "sog"]
    )
    assert result.exit_code == 0
    assert json.loads(result.output) == NARROW_RESULT
    assert '\n  "values"' in result.output


def test_query_raw_to_file(runner, mocker, tmp_path):
    body = json.dumps(NARROW_RESULT)
    mocker.patch("niquests.Session.get", return_value=_raw_response(body))
    out = tmp_path / "raw.json"
    result = runner.invoke(
        cli, ["query", *ARGS, "--format=raw", f"--output={out}", "sog"]
    )
    assert result.exit_code == 0
    assert out.read_text() == body


def test_query_raw_stream_error_midway(runner, mocker):
    resp = _raw_response(json.dumps(NARROW_RESULT))
    resp.iter_content.side_effect = niquests.ConnectionError("connection reset")
    mocker.patch("niquests.Session.get", return_value=resp)
    result = runner.invoke(cli, ["query", *ARGS, "--format=raw", "sog"])
    assert result.exit_code == 1
    assert "Error fetching history: connection reset" in result.output


def test_query_feather_file_inferred_from_extension(runner, mocker, tmp_path):
    feather = pytest.importorskip("pyarrow.feather")
    _serve(mocker, {"/values": WIDE_RESULT})
    out = tmp_path / "out.feather"
    result = runner.invoke(cli, ["query", *ARGS, f"--output={out}", "sog"])
    assert result.exit_code == 0, result.output
    assert f"Wrote {out}" in result.output
    assert "2 rows, 1 unique path(s)" in result.output
    assert feather.read_table(out).column("max_value").to_pylist() == [2.5, 2.0]


@pytest.mark.parametrize(
    ("fmt", "suffix"), [("csv", ".csv"), ("json", ".json"), ("raw", ".json")]
)
def test_query_auto_named_output(runner, mocker, monkeypatch, tmp_path, fmt, suffix):
    body = json.dumps(WIDE_RESULT)
    mocker.patch("niquests.Session.get", return_value=_raw_response(body))
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(cli, ["query", *ARGS, f"--format={fmt}", "sog", "-o"])
    assert result.exit_code == 0, result.output
    files = list(tmp_path.iterdir())
    assert len(files) == 1
    assert files[0].name.startswith("signalk-history-testserver-")
    assert files[0].suffix == suffix


def test_query_json_extension_infers_json(runner, mocker, tmp_path):
    _serve(mocker, {"/values": WIDE_RESULT})
    out = tmp_path / "x.json"
    result = runner.invoke(cli, ["query", *ARGS, f"--output={out}", "sog"])
    assert result.exit_code == 0
    assert "Format:      json" in result.output
    assert isinstance(json.loads(out.read_text()), list)


# ---------------------------------------------------------------------------
# query: path resolution and errors
# ---------------------------------------------------------------------------


def test_query_expands_patterns(runner, mocker):
    get = _serve(mocker, {"/paths": SERVER_PATHS, "/values": WIDE_RESULT})
    result = runner.invoke(cli, ["query", *ARGS, "navigation.*"])
    assert result.exit_code == 0
    values_call = get.call_args_list[-1]
    assert values_call.kwargs["params"]["paths"].startswith(
        "navigation.speedOverGround:min"
    )


def test_query_no_paths_matched(runner, mocker):
    _serve(mocker, {"/paths": SERVER_PATHS})
    result = runner.invoke(cli, ["query", *ARGS, "nothing.*"])
    assert result.exit_code == 1
    assert "No paths matched" in result.output


def test_query_error_resolving_paths(runner, mocker):
    mocker.patch("niquests.Session.get", return_value=_http_error("paths broke"))
    result = runner.invoke(cli, ["query", *ARGS, "navigation.*"])
    assert result.exit_code == 1
    assert "Error resolving paths: paths broke" in result.output


def test_query_default_provider_shown(runner, mocker):
    _serve(mocker, {"/_providers/_default": {"id": "parquet"}, "/values": WIDE_RESULT})
    result = runner.invoke(
        cli, ["query", "--host=testserver", "--no-cache", "--duration=PT1H", "sog"]
    )
    assert result.exit_code == 0
    assert "Provider:    parquet" in result.output


# ---------------------------------------------------------------------------
# cardinality
# ---------------------------------------------------------------------------


def test_cardinality_csv(runner, mocker):
    _serve(mocker, {"/values": CARDINALITY_NARROW_RESULT})
    result = runner.invoke(cli, ["cardinality", *ARGS, "--bare", "sog"])
    assert result.exit_code == 0
    lines = result.output.splitlines()
    assert lines[0].startswith("path,distinct_values")
    assert lines[1] == "navigation.speedOverGround,3,3,1,1,0.0,2.0,1.25"


def test_cardinality_json_no_header_ignored(runner, mocker):
    _serve(mocker, {"/values": CARDINALITY_NARROW_RESULT})
    result = runner.invoke(
        cli, ["cardinality", *ARGS, "--format=json", "--bare", "sog"]
    )
    assert result.exit_code == 0
    assert json.loads(result.output)[0]["nulls"] == "1"


def test_cardinality_no_header(runner, mocker):
    _serve(mocker, {"/values": CARDINALITY_NARROW_RESULT})
    result = runner.invoke(cli, ["cardinality", *ARGS, "--no-header", "--bare", "sog"])
    assert result.output.startswith("navigation.speedOverGround,")


def test_cardinality_defaults_to_all_paths(runner, mocker):
    get = _serve(mocker, {"/paths": SERVER_PATHS, "/values": CARDINALITY_NARROW_RESULT})
    result = runner.invoke(cli, ["cardinality", *ARGS])
    assert result.exit_code == 0
    assert get.call_args_list[-1].kwargs["params"]["paths"] == ",".join(
        sorted(SERVER_PATHS)
    )
    assert "1 path(s)" in result.output


def test_cardinality_no_paths_matched(runner, mocker):
    _serve(mocker, {"/paths": []})
    result = runner.invoke(cli, ["cardinality", *ARGS])
    assert result.exit_code == 1
    assert "No paths matched" in result.output


def test_cardinality_fetch_error(runner, mocker):
    mocker.patch("niquests.Session.get", return_value=_http_error("too much data"))
    result = runner.invoke(cli, ["cardinality", *ARGS, "sog"])
    assert result.exit_code == 1
    assert "Error fetching history: too much data" in result.output


# ---------------------------------------------------------------------------
# list commands
# ---------------------------------------------------------------------------


def test_list_paths_json(runner, mocker):
    _serve(mocker, {"/paths": SERVER_PATHS})
    result = runner.invoke(cli, ["list-paths", *ARGS, "--format=json", "--bare"])
    assert json.loads(result.output) == [{"path": p} for p in sorted(SERVER_PATHS)]


def test_list_paths_raw(runner, mocker):
    body = json.dumps(SERVER_PATHS)
    mocker.patch("niquests.Session.get", return_value=_raw_response(body))
    result = runner.invoke(cli, ["list-paths", *ARGS, "--format=raw", "--bare"])
    assert result.output == body + "\n"


def test_list_paths_error(runner, mocker):
    mocker.patch("niquests.Session.get", return_value=_http_error("nope"))
    result = runner.invoke(cli, ["list-paths", *ARGS])
    assert result.exit_code == 1
    assert "Error fetching paths: nope" in result.output


def test_list_contexts_json_and_raw(runner, mocker):
    _serve(mocker, {"/contexts": ["vessels.b", "vessels.a"]})
    result = runner.invoke(cli, ["list-contexts", *ARGS, "--format=json", "--bare"])
    assert json.loads(result.output) == [
        {"context": "vessels.a"},
        {"context": "vessels.b"},
    ]

    mocker.patch("niquests.Session.get", return_value=_raw_response('["vessels.a"]'))
    result = runner.invoke(cli, ["list-contexts", *ARGS, "--format=raw", "--bare"])
    assert result.output == '["vessels.a"]\n'


def test_list_contexts_error(runner, mocker):
    mocker.patch("niquests.Session.get", return_value=_http_error("nope"))
    result = runner.invoke(cli, ["list-contexts", *ARGS])
    assert result.exit_code == 1
    assert "Error fetching contexts: nope" in result.output


def test_list_providers_json_and_raw(runner, mocker):
    providers = {"b": {"isDefault": False}, "a": {"isDefault": True}}
    _serve(mocker, {"/_providers": providers})
    result = runner.invoke(
        cli, ["list-providers", "--host=testserver", "--format=json", "--bare"]
    )
    assert json.loads(result.output) == [
        {"provider": "a", "isDefault": True},
        {"provider": "b", "isDefault": False},
    ]

    mocker.patch(
        "niquests.Session.get", return_value=_raw_response(json.dumps(providers))
    )
    result = runner.invoke(
        cli, ["list-providers", "--host=testserver", "--format=raw", "--bare"]
    )
    assert json.loads(result.output) == providers


def test_list_providers_error(runner, mocker):
    mocker.patch("niquests.Session.get", return_value=_http_error("nope"))
    result = runner.invoke(cli, ["list-providers", "--host=testserver"])
    assert result.exit_code == 1
    assert "Error fetching providers: nope" in result.output


@pytest.mark.parametrize(
    ("fmt", "message"),
    [("feather", "only available on the `query` command"), ("xml", "is not one of")],
)
def test_list_format_rejected(runner, fmt, message):
    result = runner.invoke(cli, ["list-paths", *ARGS, f"--format={fmt}"])
    assert result.exit_code == 2
    assert message in result.output


def test_list_format_case_insensitive(runner, mocker):
    _serve(mocker, {"/paths": SERVER_PATHS})
    result = runner.invoke(cli, ["list-paths", *ARGS, "--format=JSON", "--bare"])
    assert result.exit_code == 0
    assert json.loads(result.output)
