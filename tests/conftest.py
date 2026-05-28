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

CARDINALITY_NARROW_RESULT = {
    "values": [{"path": "navigation.speedOverGround"}],
    "data": [
        ["2026-05-27T10:00:00Z", 1.5],
        ["2026-05-27T10:01:00Z", 2.0],
        ["2026-05-27T10:02:00Z", 1.5],
        ["2026-05-27T10:03:00Z", 0.0],
        ["2026-05-27T10:04:00Z", None],
    ],
}

CARDINALITY_POSITION_RESULT = {
    "values": [{"path": "navigation.position"}],
    "data": [
        ["2026-05-27T10:00:00Z", [51.5, -0.1]],
        ["2026-05-27T10:01:00Z", [51.6, -0.2]],
        ["2026-05-27T10:02:00Z", None],
    ],
}

POSITION_WIDE_RESULT = {
    "values": [
        {"path": "navigation.position", "method": "mid"},
    ],
    "data": [
        ["2026-05-27T10:00:00Z", [51.5, -0.1]],
        ["2026-05-27T10:01:00Z", [51.6, -0.2]],
    ],
}

GENERIC_ARRAY_WIDE_RESULT = {
    "values": [
        {"path": "navigation.gnss.satellites", "method": "mid"},
    ],
    "data": [
        ["2026-05-27T10:00:00Z", [10, 20, 30]],
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


def make_response(json_data: object, status_code: int = 200) -> MagicMock:
    """Build a minimal mock niquests response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    return resp


def url_dispatcher(routes: dict[str, object]):
    """Return a side_effect function that routes by URL substring."""

    def _dispatch(url: str, **kwargs: object) -> MagicMock:
        for fragment, payload in routes.items():
            if fragment in url:
                return make_response(payload)
        raise AssertionError(f"Unexpected URL in test: {url}")

    return _dispatch


@pytest.fixture
def server_paths() -> list[str]:
    return [
        "navigation.speedOverGround",
        "navigation.courseOverGroundTrue",
        "environment.wind.speedApparent",
    ]
