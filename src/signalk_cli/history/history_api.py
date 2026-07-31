"""SignalK v2 History API client."""

import fnmatch
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import click
import niquests

from ..net import (
    CACHE_DIR,
    api_error,
    discover_host,
    get_cached_host,
    normalise_host,
    save_cached_host,
)

__all__ = [
    "CACHE_DIR",
    "HISTORY_BASE",
    "api_error",
    "apply_time_default",
    "discover_host",
    "expand_paths",
    "fetch_default_provider",
    "fetch_server_paths",
    "get_cached_host",
    "get_cached_provider",
    "normalise_duration",
    "normalise_host",
    "resolve_provider",
    "save_cached_host",
    "save_cached_provider",
]

HISTORY_BASE = "/signalk/v2/api/history"

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
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    now = datetime.now(timezone.utc)

    if from_ is not None and to is not None:
        return from_, to, None
    elif from_ is not None:
        from_dt = datetime.fromisoformat(from_.replace("Z", "+00:00"))
        return from_, (from_dt + delta).strftime(fmt), None
    elif to is not None:
        to_dt = datetime.fromisoformat(to.replace("Z", "+00:00"))
        return (to_dt - delta).strftime(fmt), to, None
    else:
        return (now - delta).strftime(fmt), now.strftime(fmt), None


def apply_time_default(time_params: dict) -> dict:
    """If neither 'from' nor 'duration' is set, default to the hour ending at 'to' (or now)."""
    if "from" in time_params or "duration" in time_params:
        return time_params
    if "to" in time_params:
        try:
            to_dt = datetime.fromisoformat(time_params["to"].replace("Z", "+00:00"))
        except ValueError:
            to_dt = datetime.now(timezone.utc)
    else:
        to_dt = datetime.now(timezone.utc)
    from_dt = to_dt - timedelta(hours=1)
    result = {
        **time_params,
        "from": from_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "to": to_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    click.echo(
        f"No time range specified — defaulting to from={result['from']} to={result['to']}",
        err=True,
    )
    return result


# ---------------------------------------------------------------------------
# Provider cache (on-disk, per host)
# ---------------------------------------------------------------------------


def _cache_key(host: str) -> Path:
    safe = re.sub(r"[^\w.-]", "_", host)
    return CACHE_DIR / f"{safe}.provider"


def get_cached_provider(host: str) -> str | None:
    try:
        f = _cache_key(host)
        if f.exists():
            return f.read_text().strip() or None
    except OSError:
        pass
    return None


def save_cached_provider(host: str, provider_id: str) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _cache_key(host).write_text(provider_id)
    except OSError:
        pass


def fetch_default_provider(base_url: str) -> str:
    resp = niquests.get(f"{base_url}/_providers/_default", timeout=10)
    resp.raise_for_status()
    return resp.json()["id"]


def resolve_provider(
    host: str, base_url: str, provider: str | None, no_cache: bool
) -> str | None:
    """Return the effective provider id, fetching and caching the default if needed."""
    if provider:
        return provider
    if not no_cache:
        provider = get_cached_provider(host)
    if not provider:
        try:
            provider = fetch_default_provider(base_url)
            if not no_cache:
                save_cached_provider(host, provider)
        except niquests.HTTPError as e:
            click.echo(
                f"Warning: could not fetch default provider: {api_error(e)}", err=True
            )
    return provider


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------


def fetch_server_paths(
    base_url: str, time_params: dict, provider: str | None
) -> list[str]:
    """Fetch all paths that have data for the given time range."""
    params = {k: v for k, v in time_params.items() if v is not None}
    if provider:
        params["provider"] = provider
    resp = niquests.get(f"{base_url}/paths", params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def expand_paths(
    patterns: list[str],
    base_url: str,
    time_params: dict,
    provider: str | None,
) -> list[str]:
    """Expand path patterns to concrete paths.

    Literal paths pass through unchanged. Patterns containing regex
    metacharacters are matched against the server's /paths endpoint;
    invalid regex is retried as a glob pattern.
    """
    regex_chars = set(r".*+?[](){}|^$\\")
    literals: list[str] = []
    regexps: list[str] = []

    for p in patterns:
        if ":" in p:
            literals.append(p)  # inline spec — pass through unchanged
        elif any(c in p for c in regex_chars):
            regexps.append(p)
        else:
            literals.append(p)

    if not regexps:
        return literals

    click.echo("Resolving patterns against server paths...", err=True)
    available = fetch_server_paths(base_url, apply_time_default(time_params), provider)

    _GLOB_ONLY_RE = re.compile(
        r"^[^.+(){}|^$\\]+$"
    )  # only glob chars, no regex-specific

    def _compile(pattern: str) -> re.Pattern:
        if _GLOB_ONLY_RE.match(pattern):
            return re.compile(fnmatch.translate(pattern))
        try:
            return re.compile(pattern)
        except re.PatternError:
            click.echo(
                f"Note: '{pattern}' is not valid regex, treating as glob", err=True
            )
            return re.compile(fnmatch.translate(pattern))

    matched: set[str] = set()
    for pattern, rx in [(p, _compile(p)) for p in regexps]:
        hits = {path for path in available if rx.search(path)}
        if not hits:
            click.echo(f"Warning: '{pattern}' matched no paths", err=True)
        matched |= hits

    return literals + sorted(matched)
