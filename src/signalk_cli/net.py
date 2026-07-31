"""Shared host discovery/caching and CLI option helpers for SignalK API clients."""

import contextlib
import io
import time
from pathlib import Path

import click
import niquests
from zeroconf import ServiceBrowser, ServiceStateChange, Zeroconf

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


def api_error(exc: niquests.RequestException) -> str:
    """Return the most informative message from an API error response."""
    resp = getattr(exc, "response", None)
    if resp is not None:
        with contextlib.suppress(Exception):
            body = resp.json()
            return body.get("error") or body.get("message") or str(exc)
    return str(exc)


# ---------------------------------------------------------------------------
# Shared Click option decorators
# ---------------------------------------------------------------------------


def host_option(f):
    return click.option(
        "--host",
        default=None,
        envvar="SIGNALK_HOST",
        help="SignalK server base URL. http:// added if scheme omitted. "
        "Discovered via mDNS if omitted.",
    )(f)


def bare_option(f):
    return click.option(
        "--bare",
        is_flag=True,
        help="Suppress all informational messages, outputting data only.",
    )(f)


def stderr_ctx(bare: bool) -> contextlib.AbstractContextManager:
    return (
        contextlib.redirect_stderr(io.StringIO()) if bare else contextlib.nullcontext()
    )


def resolve_host(host: str | None, no_cache: bool = False) -> str:
    """Return a normalised host URL, discovering via mDNS if none provided."""
    if host:
        return normalise_host(host)
    if not no_cache:
        cached = get_cached_host()
        if cached:
            click.echo(f"Using cached host: {cached}", err=True)
            return cached
    click.echo("No host specified — searching for SignalK via mDNS...", err=True)
    discovered = discover_host()
    if not discovered:
        raise click.UsageError(
            "No SignalK server found via mDNS. Use --host or set SIGNALK_HOST."
        )
    click.echo(f"Discovered: {discovered}", err=True)
    if not no_cache:
        save_cached_host(discovered)
    return discovered
