"""Click helpers shared by the history and stream CLIs. Not part of the library API."""

import contextlib
import io
import logging
from collections.abc import Iterator

import click

from . import net

logger = logging.getLogger("signalk_cli")


class _ClickHandler(logging.Handler):
    """Send library log messages to stderr as plain text, like the CLI's own messages."""

    def emit(self, record: logging.LogRecord) -> None:
        click.echo(self.format(record), err=True)


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


@contextlib.contextmanager
def stderr_ctx(bare: bool) -> Iterator[None]:
    """Route library log messages to stderr for one command, or discard them all if bare."""
    handler = _ClickHandler()
    previous_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        with (
            contextlib.redirect_stderr(io.StringIO())
            if bare
            else contextlib.nullcontext()
        ):
            yield
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)


def resolve_host(host: str | None, no_cache: bool = False) -> str:
    """Return a normalised host URL, discovering via mDNS if none provided."""
    if host:
        return net.normalise_host(host)
    if not no_cache:
        cached = net.get_cached_host()
        if cached:
            click.echo(f"Using cached host: {cached}", err=True)
            return cached
    if net.Zeroconf is None:
        raise click.UsageError(
            "No host specified and mDNS discovery unavailable (zeroconf not "
            "installed). Use --host or set SIGNALK_HOST."
        )
    click.echo("No host specified — searching for SignalK via mDNS...", err=True)
    discovered = net.discover_host()
    if not discovered:
        raise click.UsageError(
            "No SignalK server found via mDNS. Use --host or set SIGNALK_HOST."
        )
    click.echo(f"Discovered: {discovered}", err=True)
    if not no_cache:
        net.save_cached_host(discovered)
    return discovered
