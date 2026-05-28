"""Tests for history_api.py — HTTP client and path expansion."""

from unittest.mock import MagicMock

import pytest

from signalk_cli.history.history_api import (
    api_error,
    apply_time_default,
    expand_paths,
    fetch_server_paths,
    normalise_host,
    resolve_provider,
)
from tests.conftest import make_response

BASE_URL = "http://testserver/signalk/v2/api/history"


# ---------------------------------------------------------------------------
# normalise_host
# ---------------------------------------------------------------------------


def test_normalise_host_adds_http():
    assert normalise_host("10.0.0.1") == "http://10.0.0.1"


def test_normalise_host_preserves_http():
    assert normalise_host("http://10.0.0.1") == "http://10.0.0.1"


def test_normalise_host_preserves_https():
    assert normalise_host("https://example.com") == "https://example.com"


# ---------------------------------------------------------------------------
# apply_time_default
# ---------------------------------------------------------------------------


def test_apply_time_default_passthrough_with_from():
    params = {"from": "2026-05-27T00:00:00Z"}
    assert apply_time_default(params) is params


def test_apply_time_default_passthrough_with_duration():
    params = {"duration": "PT1H"}
    assert apply_time_default(params) is params


def test_apply_time_default_sets_one_hour_window():
    result = apply_time_default({})
    assert "from" in result and "to" in result
    from datetime import datetime

    t_from = datetime.fromisoformat(result["from"].replace("Z", "+00:00"))
    t_to = datetime.fromisoformat(result["to"].replace("Z", "+00:00"))
    diff = (t_to - t_from).total_seconds()
    assert diff == pytest.approx(3600, abs=5)


def test_apply_time_default_uses_given_to():
    result = apply_time_default({"to": "2026-05-27T12:00:00Z"})
    assert result["to"] == "2026-05-27T12:00:00Z"
    assert result["from"] == "2026-05-27T11:00:00Z"


# ---------------------------------------------------------------------------
# api_error
# ---------------------------------------------------------------------------


def test_api_error_extracts_error_key():
    resp = MagicMock()
    resp.json.return_value = {"error": "path not found"}
    exc = MagicMock()
    exc.response = resp
    assert api_error(exc) == "path not found"


def test_api_error_extracts_message_key():
    resp = MagicMock()
    resp.json.return_value = {"message": "server error"}
    exc = MagicMock()
    exc.response = resp
    assert api_error(exc) == "server error"


def test_api_error_no_response():
    exc = MagicMock()
    exc.response = None
    exc.__str__ = lambda self: "connection refused"
    assert api_error(exc) == "connection refused"


# ---------------------------------------------------------------------------
# fetch_server_paths
# ---------------------------------------------------------------------------


def test_fetch_server_paths(mocker):
    paths = ["navigation.speedOverGround", "navigation.courseOverGroundTrue"]
    mocker.patch(
        "signalk_cli.history.history_api.niquests.get",
        return_value=make_response(paths),
    )
    result = fetch_server_paths(BASE_URL, {"from": "2026-05-27T10:00:00Z"}, "mydb")
    assert result == paths


# ---------------------------------------------------------------------------
# expand_paths
# ---------------------------------------------------------------------------


def test_expand_paths_no_regex_chars_no_http(mocker):
    # Paths without regex metacharacters or colons are passed through as literals
    mock_get = mocker.patch("signalk_cli.history.history_api.niquests.get")
    result = expand_paths(
        ["depth", "speed"],
        BASE_URL,
        {"from": "2026-05-27T10:00:00Z"},
        None,
    )
    mock_get.assert_not_called()
    assert result == ["depth", "speed"]


def test_expand_paths_inline_spec_no_http(mocker):
    mock_get = mocker.patch("signalk_cli.history.history_api.niquests.get")
    result = expand_paths(
        ["navigation.speedOverGround:max"],
        BASE_URL,
        {"from": "2026-05-27T10:00:00Z"},
        None,
    )
    mock_get.assert_not_called()
    assert result == ["navigation.speedOverGround:max"]


def test_expand_paths_glob_matches(mocker, server_paths):
    mocker.patch(
        "signalk_cli.history.history_api.niquests.get",
        return_value=make_response(server_paths),
    )
    result = expand_paths(["*"], BASE_URL, {"from": "2026-05-27T10:00:00Z"}, None)
    assert set(result) == set(server_paths)


def test_expand_paths_regex_matches(mocker, server_paths):
    mocker.patch(
        "signalk_cli.history.history_api.niquests.get",
        return_value=make_response(server_paths),
    )
    result = expand_paths(
        ["navigation\\..*"], BASE_URL, {"from": "2026-05-27T10:00:00Z"}, None
    )
    assert set(result) == {
        "navigation.speedOverGround",
        "navigation.courseOverGroundTrue",
    }


def test_expand_paths_no_match_warns(mocker, server_paths, capsys):
    mocker.patch(
        "signalk_cli.history.history_api.niquests.get",
        return_value=make_response(server_paths),
    )
    result = expand_paths(
        ["nonexistent.*"], BASE_URL, {"from": "2026-05-27T10:00:00Z"}, None
    )
    assert result == []


# ---------------------------------------------------------------------------
# resolve_provider
# ---------------------------------------------------------------------------


def test_resolve_provider_explicit(mocker):
    mock_get = mocker.patch("signalk_cli.history.history_api.niquests.get")
    result = resolve_provider("http://server", BASE_URL, "mydb", no_cache=True)
    mock_get.assert_not_called()
    assert result == "mydb"


def test_resolve_provider_fetches_default(mocker):
    mocker.patch(
        "signalk_cli.history.history_api.niquests.get",
        return_value=make_response({"id": "signalk-parquet"}),
    )
    result = resolve_provider("http://server", BASE_URL, None, no_cache=True)
    assert result == "signalk-parquet"
