"""Tests for errors.py — SignalKError and api_error."""

from unittest.mock import MagicMock

import niquests

from signalk_cli.errors import SignalKError, api_error


def test_from_request_uses_server_error_and_status():
    resp = MagicMock()
    resp.status_code = 404
    resp.json.return_value = {"error": "path not found"}
    exc = niquests.HTTPError("404 Client Error")
    exc.response = resp

    err = SignalKError.from_request(exc)

    assert str(err) == "path not found"
    assert err.status_code == 404


def test_from_request_without_response():
    err = SignalKError.from_request(niquests.ConnectionError("connection refused"))
    assert str(err) == "connection refused"
    assert err.status_code is None


def test_from_request_falls_back_when_body_not_json():
    resp = MagicMock()
    resp.status_code = 502
    resp.json.side_effect = ValueError("not json")
    exc = niquests.HTTPError("502 Bad Gateway")
    exc.response = resp

    err = SignalKError.from_request(exc)

    assert str(err) == "502 Bad Gateway"
    assert err.status_code == 502


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
    exc.__str__.return_value = "connection refused"
    assert api_error(exc) == "connection refused"
