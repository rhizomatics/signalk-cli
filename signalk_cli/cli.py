"""Click CLI for the SignalK v2 History API."""

import re
import sys
from datetime import datetime, timezone
from urllib.parse import urlparse

import click
import niquests

from .history_api import (
    HISTORY_BASE,
    api_error,
    apply_time_default,
    expand_paths,
    fetch_server_paths,
    normalise_host,
    resolve_provider,
)
from .output import csv_sink, write_csv, write_feather


# ---------------------------------------------------------------------------
# Shared option decorators
# ---------------------------------------------------------------------------

def _host_option(f):
    return click.option(
        "--host", required=True, envvar="SIGNALK_HOST",
        help="SignalK server base URL. http:// added if scheme omitted.",
    )(f)


def _provider_options(f):
    f = click.option("--no-cache", is_flag=True, help="Ignore cached default provider")(f)
    f = click.option("--provider", help="History provider plugin id (default fetched and cached automatically)")(f)
    return f


def _time_options(f):
    f = click.option("--duration", metavar="DURATION", help="Duration: integer seconds or ISO 8601 (e.g. PT15M, 3600)")(f)
    f = click.option("--to", metavar="DATETIME", help="End of range (ISO 8601)")(f)
    f = click.option("--from", "from_", metavar="DATETIME", help="Start of range (ISO 8601)")(f)
    return f


def _build_time_params(from_: str | None, to: str | None, duration: str | None) -> dict:
    p: dict = {}
    if from_:
        p["from"] = from_
    if to:
        p["to"] = to
    if duration:
        p["duration"] = duration
    return p


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------

@click.group(context_settings={"help_option_names": ["-h", "--help"]})
def cli():
    """SignalK v2 history CLI."""


# ---------------------------------------------------------------------------
# query
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("paths", nargs=-1, required=True, metavar="PATH...")
@_host_option
@_time_options
@click.option("--resolution", metavar="RESOLUTION",
              help="Sample window: integer seconds or time expression (1s, 1m, 1h, 1d)")
@click.option("--context", default="vessels.self", show_default=True, help="SignalK context")
@_provider_options
@click.option("--format", "fmt", default="csv", show_default=True,
              type=click.Choice(["csv", "feather"], case_sensitive=False),
              help="Output format")
@click.option("--no-header", is_flag=True, help="Suppress header row (CSV only)")
@click.option("--output", "-o", default=None, metavar="FILE",
              help="Output file (default: signalk-history-<server>-<timestamp>.<ext>, use - for stdout)")
@click.option("--stdout", is_flag=True,
              help="Also print to stdout; when no --output given, stdout only (CSV only)")
def query(paths, host, from_, to, duration, resolution, context, provider, no_cache,
          fmt, no_header, output, stdout):
    """Query history and write results as CSV or Feather.

    PATH arguments may be literal SignalK paths or Python regex/glob patterns.
    Patterns are resolved against the server's /paths endpoint first.

    \b
    Examples:
      signalk-history query --host 10.36.10.21 --duration PT1H navigation.speedOverGround
      signalk-history query --host 10.36.10.21 --duration PT1H --format feather '*'
      signalk-history query --host 10.36.10.21 --from 2026-05-26T00:00:00Z --to 2026-05-27T00:00:00Z '*'
    """
    if fmt == "feather" and stdout:
        raise click.UsageError("--stdout is not supported for feather output (binary format)")

    host = normalise_host(host)
    base_url = host.rstrip("/") + HISTORY_BASE
    provider = resolve_provider(host, base_url, provider, no_cache)
    time_params = apply_time_default(_build_time_params(from_, to, duration))

    click.echo(f"Server:     {host}", err=True)
    click.echo(f"Provider:   {provider or '(none)'}", err=True)
    click.echo(f"From:       {time_params.get('from', '(server default)')}", err=True)
    click.echo(f"To:         {time_params.get('to', '(server default)')}", err=True)
    click.echo(f"Duration:   {time_params.get('duration', '(not specified)')}", err=True)
    click.echo(f"Resolution: {resolution or '(server default)'}", err=True)
    click.echo(f"Format:     {fmt}", err=True)

    try:
        resolved = expand_paths(list(paths), base_url, time_params, provider)
    except niquests.RequestException as e:
        click.echo(f"Error resolving paths: {api_error(e)}", err=True)
        sys.exit(1)

    if not resolved:
        click.echo("No paths matched — nothing to query.", err=True)
        sys.exit(1)

    params: dict = {**time_params, "paths": ",".join(resolved), "context": context}
    if resolution:
        params["resolution"] = resolution
    if provider:
        params["provider"] = provider

    try:
        resp = niquests.get(f"{base_url}/values", params=params, timeout=60)
        resp.raise_for_status()
    except niquests.RequestException as e:
        click.echo(f"Error fetching history: {api_error(e)}", err=True)
        sys.exit(1)

    result = resp.json()

    explicit_file = bool(output and output != "-")
    if output is None:
        server_name = urlparse(host).hostname or re.sub(r"[^\w.-]", "_", host)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        ext = "feather" if fmt == "feather" else "csv"
        output = f"signalk-history-{server_name}-{ts}.{ext}"
        explicit_file = True

    write_to_stdout = stdout or (output == "-")
    write_to_file = explicit_file

    if fmt == "feather":
        row_count, unique_paths = write_feather(result, output)
    else:
        file_fh, sink = csv_sink(output, write_to_file, write_to_stdout)
        try:
            row_count, unique_paths = write_csv(result, sink, no_header)
        finally:
            if file_fh:
                file_fh.close()

    if write_to_file:
        click.echo(f"Wrote {output}", err=True)
    click.echo(
        f"{row_count} rows, {len(unique_paths)} unique path(s): {', '.join(sorted(unique_paths))}",
        err=True,
    )


# ---------------------------------------------------------------------------
# list-paths
# ---------------------------------------------------------------------------

@cli.command("list-paths")
@_host_option
@_time_options
@_provider_options
@click.option("--context", default="vessels.self", show_default=True, help="SignalK context")
def list_paths(host, from_, to, duration, provider, no_cache, context):
    """List paths that have data for the given time range."""
    host = normalise_host(host)
    base_url = host.rstrip("/") + HISTORY_BASE
    provider = resolve_provider(host, base_url, provider, no_cache)
    time_params = apply_time_default(_build_time_params(from_, to, duration))

    click.echo(f"Server:   {host}", err=True)
    click.echo(f"Provider: {provider or '(none)'}", err=True)
    click.echo(f"From:     {time_params.get('from', '(server default)')}", err=True)
    click.echo(f"To:       {time_params.get('to', '(server default)')}", err=True)
    click.echo(f"Duration: {time_params.get('duration', '(not specified)')}", err=True)

    try:
        paths = fetch_server_paths(base_url, time_params, provider)
    except niquests.RequestException as e:
        click.echo(f"Error fetching paths: {api_error(e)}", err=True)
        sys.exit(1)

    for path in sorted(paths):
        click.echo(path)

    click.echo(f"{len(paths)} path(s)", err=True)


# ---------------------------------------------------------------------------
# list-providers
# ---------------------------------------------------------------------------

@cli.command("list-providers")
@_host_option
def list_providers(host):
    """List registered history providers."""
    host = normalise_host(host)
    base_url = host.rstrip("/") + HISTORY_BASE
    click.echo(f"Server: {host}", err=True)

    try:
        resp = niquests.get(f"{base_url}/_providers", timeout=10)
        resp.raise_for_status()
    except niquests.RequestException as e:
        click.echo(f"Error fetching providers: {api_error(e)}", err=True)
        sys.exit(1)

    providers: dict = resp.json()
    for pid, info in sorted(providers.items()):
        marker = " (default)" if info.get("isDefault") else ""
        click.echo(f"{pid}{marker}")

    click.echo(f"{len(providers)} provider(s)", err=True)


# ---------------------------------------------------------------------------
# list-contexts
# ---------------------------------------------------------------------------

@cli.command("list-contexts")
@_host_option
@_time_options
@_provider_options
def list_contexts(host, from_, to, duration, provider, no_cache):
    """List contexts that have historical data for the given time range."""
    host = normalise_host(host)
    base_url = host.rstrip("/") + HISTORY_BASE
    provider = resolve_provider(host, base_url, provider, no_cache)
    time_params = apply_time_default(_build_time_params(from_, to, duration))

    click.echo(f"Server:   {host}", err=True)
    click.echo(f"Provider: {provider or '(none)'}", err=True)
    click.echo(f"From:     {time_params.get('from', '(server default)')}", err=True)
    click.echo(f"To:       {time_params.get('to', '(server default)')}", err=True)
    click.echo(f"Duration: {time_params.get('duration', '(not specified)')}", err=True)

    params = {**time_params}
    if provider:
        params["provider"] = provider

    try:
        resp = niquests.get(f"{base_url}/contexts", params=params, timeout=30)
        resp.raise_for_status()
    except niquests.RequestException as e:
        click.echo(f"Error fetching contexts: {api_error(e)}", err=True)
        sys.exit(1)

    contexts: list = resp.json()
    for ctx in sorted(contexts):
        click.echo(ctx)

    click.echo(f"{len(contexts)} context(s)", err=True)
