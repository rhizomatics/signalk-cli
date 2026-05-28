"""Shared fixtures and test data."""

from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Representative API payloads
# ---------------------------------------------------------------------------

WIDE_RESULT = {
    "values": [
        {"path": "navigation.speedOverGround", "method": "min"},
        {"path": "navigation.speedOverGround", "method": "average"},
        {"path": "navigation.speedOverGround", "method": "max"},
    ],
    "data": [
        ["2026-05-27T10:00:00Z", 1.5, 2.0, 2.5],
        ["2026-05-27T10:01:00Z", 1.0, 1.5, 2.0],
    ],
}

NARROW_RESULT = {
    "values": [
        {"path": "navigation.speedOverGround"},
    ],
    "data": [
        ["2026-05-27T10:00:00Z", 1.5],
        ["2026-05-27T10:01:00Z", 2.0],
    ],
}

MULTI_PATH_WIDE_RESULT = {
    "values": [
        {"path": "navigation.speedOverGround", "method": "min"},
        {"path": "navigation.speedOverGround", "method": "average"},
        {"path": "navigation.speedOverGround", "method": "max"},
        {"path": "navigation.courseOverGroundTrue", "method": "min"},
        {"path": "navigation.courseOverGroundTrue", "method": "average"},
        {"path": "navigation.courseOverGroundTrue", "method": "max"},
    ],
    "data": [
        ["2026-05-27T10:00:00Z", 1.5, 2.0, 2.5, 45.0, 90.0, 135.0],
    ],
}


def make_response(json_data, status_code=200):
    """Build a minimal mock niquests response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    return resp


def url_dispatcher(routes: dict):
    """Return a side_effect function that routes by URL substring."""

    def _dispatch(url, **kwargs):
        for fragment, payload in routes.items():
            if fragment in url:
                return make_response(payload)
        raise AssertionError(f"Unexpected URL in test: {url}")

    return _dispatch


@pytest.fixture
def server_paths():
    return [
        "navigation.speedOverGround",
        "navigation.courseOverGroundTrue",
        "environment.wind.speedApparent",
    ]
