"""SignalK v2 History API client."""

import fnmatch
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import click
import niquests
from zeroconf import ServiceBrowser, ServiceStateChange, Zeroconf

HISTORY_BASE = "/signalk/v2/api/history"
CACHE_DIR = Path.home() / ".cache" / "signalk-cli"
_SIGNALK_TYPE = "_signalk-ws._tcp.local."
_HOST_CACHE_FILE = CACHE_DIR / "host.cache"


def get_cached_host() -> str | None:
    try:
        if _HOST_CACHE_FILE.exists():
            return _HOST_CACHE_FILE.read_text().strip() or None
    except OSError:
        pass
    return None


def save_cached_host(host: str) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _HOST_CACHE_FILE.write_text(host)
    except OSError:
        pass


def discover_host(timeout: float = 5.0) -> str | None:
    """Browse mDNS for a SignalK server and return its base URL, or None."""
    found: list[str] = []

    def _on_change(
        zeroconf: Zeroconf,
        service_type: str,
        name: str,
        state_change: ServiceStateChange,
    ) -> None:
        if state_change is not ServiceStateChange.Added:
            return
        info = zeroconf.get_service_info(service_type, name)
        if info is None:
            return
        addrs = info.parsed_addresses()
        if not addrs:
            return
        host = f"http://{addrs[0]}:{info.port}"
        found.append(host)

    zc = Zeroconf()
    try:
        ServiceBrowser(zc, _SIGNALK_TYPE, handlers=[_on_change])
        import time

        deadline = time.monotonic() + timeout
        while not found and time.monotonic() < deadline:
            time.sleep(0.1)
    finally:
        zc.close()

    return found[0] if found else None


def normalise_host(host: str) -> str:
    """Prepend http:// if the host has no scheme."""
    if "://" not in host:
        return f"http://{host}"
    return host


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


def api_error(exc: niquests.RequestException) -> str:
    """Return the most informative message from an API error response."""
    resp = getattr(exc, "response", None)
    if resp is not None:
        try:
            body = resp.json()
            return body.get("error") or body.get("message") or str(exc)
        except Exception as e:
            logging.debug("Error handling API error: %s", e)
    return str(exc)


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

    def _compile(pattern: str) -> re.Pattern:
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
