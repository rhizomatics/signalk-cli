"""Time ranges for History API requests."""

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

logger = logging.getLogger("signalk_cli")

_TIMESTAMP_FMT = "%Y-%m-%dT%H:%M:%SZ"

_DURATION_RE = re.compile(
    r"^P(?:(\d+)Y)?(?:(\d+)M)?(?:(\d+)W)?(?:(\d+)D)?"
    r"(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?)?$"
)


def _has_date_parts(duration: str) -> bool:
    m = _DURATION_RE.match(duration)
    return bool(m and any(m.group(i) for i in (1, 2, 3, 4)))


def _duration_to_timedelta(duration: str) -> timedelta:
    m = _DURATION_RE.match(duration)
    if not m:
        raise ValueError(f"Cannot parse duration: {duration!r}")
    years, months, weeks, days, hours, minutes = (
        int(m.group(i) or 0) for i in range(1, 7)
    )
    secs = float(m.group(7) or 0)
    return timedelta(
        days=years * 365 + months * 30 + weeks * 7 + days,
        hours=hours,
        minutes=minutes,
        seconds=secs,
    )


def normalise_duration(
    duration: str | None, from_: str | None, to: str | None
) -> tuple[str | None, str | None, str | None]:
    """Convert date-component durations to explicit from/to timestamps.

    SignalK only accepts PT-prefix (time-only) durations. Durations containing
    Y/M/W/D are expanded to from/to pairs:
      from + duration  →  to = from + duration
      to + duration    →  from = to - duration
      duration alone   →  from = now - duration, to = now

    Returns (from_, to, duration_or_None).
    """
    if not duration:
        return from_, to, duration
    try:
        int(duration)
        return from_, to, duration  # integer seconds, pass through
    except ValueError:
        pass
    if not _has_date_parts(duration):
        return from_, to, duration  # PT-only, pass through

    delta = _duration_to_timedelta(duration)
    fmt = _TIMESTAMP_FMT
    now = datetime.now(UTC)

    if from_ is not None and to is not None:
        return from_, to, None
    elif from_ is not None:
        from_dt = datetime.fromisoformat(from_)
        return from_, (from_dt + delta).strftime(fmt), None
    elif to is not None:
        to_dt = datetime.fromisoformat(to)
        return (to_dt - delta).strftime(fmt), to, None
    else:
        return (now - delta).strftime(fmt), now.strftime(fmt), None


def apply_time_default(time_params: dict) -> dict:
    """If neither 'from' nor 'duration' is set, default to the hour ending at 'to' (or now)."""
    if "from" in time_params or "duration" in time_params:
        return time_params
    if "to" in time_params:
        try:
            to_dt = datetime.fromisoformat(time_params["to"])
        except ValueError:
            to_dt = datetime.now(UTC)
    else:
        to_dt = datetime.now(UTC)
    from_dt = to_dt - timedelta(hours=1)
    result = {
        **time_params,
        "from": from_dt.strftime(_TIMESTAMP_FMT),
        "to": to_dt.strftime(_TIMESTAMP_FMT),
    }
    logger.info(
        "No time range specified — defaulting to from=%s to=%s",
        result["from"],
        result["to"],
    )
    return result


def _format_time(value: str | datetime | None) -> str | None:
    if value is None or isinstance(value, str):
        return value
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).strftime(_TIMESTAMP_FMT)


def _format_duration(value: str | int | timedelta | None) -> str | None:
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, timedelta):
        seconds = value.total_seconds()
        return str(int(seconds)) if seconds.is_integer() else f"PT{seconds}S"
    return str(value)


@dataclass(frozen=True)
class TimeRange:
    """The time window for a History API request.

    Any combination of start, end and duration may be given, as
    the History API allows. Timestamps may be ISO 8601 strings or datetimes
    (naive datetimes are taken as UTC). Durations may be ISO 8601 strings
    (PT15M, P1D), integer seconds, or timedeltas.

    Example:
        >>> last_hour = TimeRange(duration="PT1H")
        >>> one_day = TimeRange(start="2026-05-27T00:00:00Z", duration="P1D")
    """

    start: str | datetime | None = None
    end: str | datetime | None = None
    duration: str | int | timedelta | None = None

    def resolved(self) -> "TimeRange":
        """Return an equivalent range the server accepts, with all values as strings.

        The server only accepts time-only durations (PT...), so durations
        with date parts (P1D, P1W) are expanded to explicit start and
        end timestamps. With no start and no duration, the range defaults to
        the hour ending at end, or now.
        """
        start, end, duration = normalise_duration(
            _format_duration(self.duration),
            _format_time(self.start),
            _format_time(self.end),
        )
        params = apply_time_default(_params(start, end, duration))
        return TimeRange(
            start=params.get("from"),
            end=params.get("to"),
            duration=params.get("duration"),
        )

    def params(self) -> dict[str, str]:
        """Return the from/to/duration query parameters for this range, as given."""
        return _params(
            _format_time(self.start),
            _format_time(self.end),
            _format_duration(self.duration),
        )


def _params(start: str | None, end: str | None, duration: str | None) -> dict[str, str]:
    p: dict[str, str] = {}
    if start:
        p["from"] = start
    if end:
        p["to"] = end
    if duration:
        p["duration"] = duration
    return p
