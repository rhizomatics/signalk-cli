"""SignalK v2 History API client."""

import fnmatch
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import click
import niquests

HISTORY_BASE = "/signalk/v2/api/history"
CACHE_DIR = Path.home() / ".cache" / "signalk-history-cli"


def normalise_host(host: str) -> str:
    """Prepend http:// if the host has no scheme."""
    if "://" not in host:
        return f"http://{host}"
    return host


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
        "to":   to_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
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
        except Exception:
            pass
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


def resolve_provider(host: str, base_url: str, provider: str | None, no_cache: bool) -> str | None:
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
            click.echo(f"Warning: could not fetch default provider: {api_error(e)}", err=True)
    return provider


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

def fetch_server_paths(base_url: str, time_params: dict, provider: str | None) -> list[str]:
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
        if any(c in p for c in regex_chars):
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
            click.echo(f"Note: '{pattern}' is not valid regex, treating as glob", err=True)
            return re.compile(fnmatch.translate(pattern))

    matched: set[str] = set()
    for pattern, rx in [(p, _compile(p)) for p in regexps]:
        hits = {path for path in available if rx.search(path)}
        if not hits:
            click.echo(f"Warning: '{pattern}' matched no paths", err=True)
        matched |= hits

    return literals + sorted(matched)
