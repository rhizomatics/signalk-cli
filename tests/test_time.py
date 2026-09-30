"""Tests for history._time — TimeRange and duration normalisation."""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from signalk_cli.history._time import TimeRange, normalise_duration


def _dt(s: str | datetime | None) -> datetime:
    assert isinstance(s, str)
    return datetime.fromisoformat(s)


# ---------------------------------------------------------------------------
# normalise_duration
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("duration", [None, "", "3600", "PT15M", "PT1H30M", "PT0.5S"])
def test_normalise_duration_passes_through_server_durations(duration):
    assert normalise_duration(duration, "2026-05-27T00:00:00Z", None) == (
        "2026-05-27T00:00:00Z",
        None,
        duration,
    )


def test_normalise_duration_from_plus_date_duration():
    assert normalise_duration("P1D", "2026-05-27T00:00:00Z", None) == (
        "2026-05-27T00:00:00Z",
        "2026-05-28T00:00:00Z",
        None,
    )


def test_normalise_duration_to_minus_date_duration():
    assert normalise_duration("P1W", None, "2026-05-27T00:00:00Z") == (
        "2026-05-20T00:00:00Z",
        "2026-05-27T00:00:00Z",
        None,
    )


def test_normalise_duration_mixed_date_and_time_parts():
    assert normalise_duration("P1DT6H", "2026-05-27T00:00:00Z", None)[1] == (
        "2026-05-28T06:00:00Z"
    )


def test_normalise_duration_years_and_months_are_approximate():
    # 1 year = 365 days, 1 month = 30 days
    assert normalise_duration("P1Y1M", "2025-01-01T00:00:00Z", None)[1] == (
        "2026-01-31T00:00:00Z"
    )


def test_normalise_duration_both_ends_given_drops_duration():
    assert normalise_duration(
        "P1D", "2026-05-27T00:00:00Z", "2026-05-29T00:00:00Z"
    ) == (
        "2026-05-27T00:00:00Z",
        "2026-05-29T00:00:00Z",
        None,
    )


def test_normalise_duration_alone_ends_now():
    start, end, duration = normalise_duration("P1D", None, None)
    assert duration is None
    assert (_dt(end) - _dt(start)) == timedelta(days=1)
    assert abs((datetime.now(UTC) - _dt(end)).total_seconds()) < 5


# ---------------------------------------------------------------------------
# TimeRange.params
# ---------------------------------------------------------------------------


def test_params_empty():
    assert TimeRange().params() == {}


def test_params_strings_pass_through():
    assert TimeRange(
        "2026-05-27T00:00:00Z", "2026-05-28T00:00:00Z", "PT1H"
    ).params() == {
        "from": "2026-05-27T00:00:00Z",
        "to": "2026-05-28T00:00:00Z",
        "duration": "PT1H",
    }


def test_params_formats_aware_datetime_as_utc():
    plus_two = timezone(timedelta(hours=2))
    tr = TimeRange(start=datetime(2026, 5, 27, 12, 0, tzinfo=plus_two))
    assert tr.params() == {"from": "2026-05-27T10:00:00Z"}


def test_params_treats_naive_datetime_as_utc():
    naive = datetime(2026, 5, 27, 12, 0)  # noqa: DTZ001
    assert TimeRange(end=naive).params() == {"to": "2026-05-27T12:00:00Z"}


@pytest.mark.parametrize(
    ("duration", "expected"),
    [
        (900, "900"),
        (timedelta(minutes=15), "900"),
        (timedelta(seconds=1.5), "PT1.5S"),
    ],
)
def test_params_formats_duration(duration, expected):
    assert TimeRange(duration=duration).params() == {"duration": expected}


# ---------------------------------------------------------------------------
# TimeRange.resolved
# ---------------------------------------------------------------------------


def test_resolved_defaults_to_last_hour(caplog):
    caplog.set_level("INFO", logger="signalk_cli")
    tr = TimeRange().resolved()
    assert tr.duration is None
    assert (_dt(tr.end) - _dt(tr.start)) == timedelta(hours=1)
    assert "defaulting to" in caplog.text


def test_resolved_defaults_to_hour_before_end():
    tr = TimeRange(end="2026-05-27T12:00:00Z").resolved()
    assert tr == TimeRange("2026-05-27T11:00:00Z", "2026-05-27T12:00:00Z")


def test_resolved_keeps_server_duration():
    assert TimeRange(duration="PT15M").resolved() == TimeRange(duration="PT15M")


def test_resolved_expands_date_duration():
    tr = TimeRange(start=datetime(2026, 5, 27, tzinfo=UTC), duration="P1D").resolved()
    assert tr == TimeRange("2026-05-27T00:00:00Z", "2026-05-28T00:00:00Z")


def test_resolved_is_idempotent():
    tr = TimeRange(start="2026-05-27T00:00:00Z", duration="P1D").resolved()
    assert tr.resolved() == tr


def test_resolved_unparseable_end_falls_back_to_now():
    tr = TimeRange(end="yesterday-ish").resolved()
    assert abs((datetime.now(UTC) - _dt(tr.end)).total_seconds()) < 5


def test_unrecognised_duration_is_left_for_the_server():
    # The server reports the error; we don't second-guess its duration syntax
    assert TimeRange(duration="banana").resolved() == TimeRange(duration="banana")
