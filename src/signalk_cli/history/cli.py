"""Click CLI for the SignalK v2 History API."""

import contextlib
import csv
import json
import re
import sys
from collections.abc import Callable, Generator, Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import click
import niquests

from .._arrow import FEATHER_EXTENSIONS, write_feather
from .._cli import bare_option, host_option, resolve_host, stderr_ctx
from ..errors import SignalKError, api_error
from ._results import CARDINALITY_COLUMNS
from ._time import TimeRange
from .api import AGGREGATION_METHODS, HistoryClient, HistoryResult
from .output import (
    cardinality_text,
    write_csv,
    write_csv_wide,
    write_json,
    write_json_wide,
)

_AUTO_OUTPUT = "__auto_output__"

# ---------------------------------------------------------------------------
# Shared option decorators
# ---------------------------------------------------------------------------


def _list_fmt_callback(
    ctx: click.Context, param: click.Parameter, value: str | None
) -> str | None:
    if value is None:
        return value
    v = value.lower()
    if v in ("csv", "json", "raw"):
        return v
    if v == "feather":
        raise click.BadParameter(
            "feather output is only available on the `query` command "
            "(requires pip install 'signalk-cli[feather]')"
        )
    raise click.BadParameter(f"'{value}' is not one of 'csv', 'json', 'raw'")


_host_option = host_option
_resolve_host = resolve_host


def _provider_options[F: Callable[..., Any]](f: F) -> F:
    f = click.option("--no-cache", is_flag=True, help="Ignore cached default provider")(
        f
    )
    f = click.option(
        "--provider",
        help="History provider plugin id (default fetched and cached automatically)",
    )(f)
    return f


def _time_options[F: Callable[..., Any]](f: F) -> F:
    f = click.option(
        "--duration",
        metavar="DURATION",
        help="Duration: integer seconds or ISO 8601 (e.g. PT15M, 3600)",
    )(f)
    f = click.option("--to", metavar="DATETIME", help="End of range (ISO 8601)")(f)
    f = click.option(
        "--from", "from_", metavar="DATETIME", help="Start of range (ISO 8601)"
    )(f)
    return f


_bare_option = bare_option
_stderr_ctx = stderr_ctx


def _client(
    host: str | None,
    provider: str | None = None,
    no_cache: bool = False,
    context: str = "vessels.self",
) -> HistoryClient:
    return HistoryClient(
        resolve_host(host, no_cache),
        provider=provider,
        context=context,
        cache=not no_cache,
    )


@contextlib.contextmanager
def _exit_on_error(doing: str) -> Generator[None]:
    """Report a failed request as 'Error <doing>: <message>' and exit 1."""
    try:
        yield
    except SignalKError as e:
        click.echo(f"Error {doing}: {e}", err=True)
        sys.exit(1)
    except niquests.RequestException as e:  # failures mid-way through a streamed body
        click.echo(f"Error {doing}: {api_error(e)}", err=True)
        sys.exit(1)


def _echo_time(time_params: dict[str, Any], width: int) -> None:
    for label, key, missing in (
        ("From:", "from", "(server default)"),
        ("To:", "to", "(server default)"),
        ("Duration:", "duration", "(not specified)"),
    ):
        click.echo(f"{label:<{width}}{time_params.get(key, missing)}", err=True)


def _summary(table_paths: Iterable[str], row_count: int) -> str:
    unique = sorted(set(table_paths))
    return f"{row_count} rows, {len(unique)} unique path(s): {', '.join(unique)}"


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
def cli() -> None:
    """SignalK v2 history CLI."""


# ---------------------------------------------------------------------------
# query
# ---------------------------------------------------------------------------


@cli.command()
@click.argument("paths", nargs=-1, required=True, metavar="PATH...")
@_host_option
@_time_options
@click.option(
    "--resolution",
    metavar="RESOLUTION",
    help="Sample window: integer seconds or time expression (1s, 1m, 1h, 1d)",
)
@click.option(
    "--context", "-c", default="vessels.self", show_default=True, help="SignalK context"
)
@_provider_options
@click.option(
    "--aggregation",
    "--agg",
    "aggregation",
    type=click.Choice(AGGREGATION_METHODS, case_sensitive=False),
    default=None,
    help=(
        "Aggregation method applied to all paths. "
        "Omit for wide mode (min/max/average columns). "
        "Paths may also carry an inline ':method[:param]' suffix."
    ),
)
@click.option(
    "--samples",
    type=int,
    default=None,
    metavar="N",
    help="Sample count for --aggregation sma",
)
@click.option(
    "--alpha",
    type=float,
    default=None,
    metavar="FLOAT",
    help="Alpha value (0-1) for --aggregation ema",
)
@click.option(
    "--format",
    "fmt",
    default=None,
    type=click.Choice(["csv", "feather", "json", "raw"], case_sensitive=False),
    help="Output format (default: inferred from --output extension, else csv)",
)
@click.option("--no-header", is_flag=True, help="Suppress header row (CSV only)")
@click.option(
    "--output",
    "-o",
    is_flag=False,
    flag_value=_AUTO_OUTPUT,
    default=None,
    metavar="FILE",
    help="Write to FILE. Omit for stdout (default). Give without a filename to auto-name the file.",
)
@click.option(
    "--pretty",
    is_flag=True,
    help="Pretty-print JSON output (json/raw formats). Buffers the full response.",
)
@_bare_option
def query(
    paths: tuple[str, ...],
    host: str | None,
    from_: str | None,
    to: str | None,
    duration: str | None,
    resolution: str | None,
    context: str,
    provider: str | None,
    no_cache: bool,
    aggregation: str | None,
    samples: int | None,
    alpha: float | None,
    fmt: str | None,
    no_header: bool,
    output: str | None,
    pretty: bool,
    bare: bool,
) -> None:
    """Query history and write results as CSV, JSON, or Feather.

    Outputs to stdout by default. Use --output to write to a file.

    PATH arguments may be literal SignalK paths, Python regex/glob patterns,
    or inline path specs with aggregation (e.g. navigation.speedOverGround:sma:5).

    Without --aggregation and without inline specs, the default is wide mode:
    min/max/average are fetched per path and written as separate columns.

    \b
    Examples:
      signalk_cli.history query --host 10.36.10.21 --duration PT1H navigation.speedOverGround
      signalk_cli.history query --host 10.36.10.21 --duration PT1H --agg sma --samples 5 '*'
      signalk_cli.history query --host 10.36.10.21 --duration PT1H navigation.speedOverGround:ema:0.2
      signalk_cli.history query --host 10.36.10.21 --from 2026-05-26T00:00:00Z --to 2026-05-27T00:00:00Z '*'
    """
    with _stderr_ctx(bare):
        client = _client(host, provider, no_cache, context)
        time = TimeRange(from_, to, duration).resolved()
        time_params = time.params()

        auto_name = output == _AUTO_OUTPUT

        # Infer format from explicit output filename extension
        if fmt is None:
            if output and output not in (_AUTO_OUTPUT, "-"):
                suffix = Path(output).suffix.lower()
                if suffix in FEATHER_EXTENSIONS:
                    fmt = "feather"
                elif suffix == ".json":
                    fmt = "json"
                else:
                    fmt = "csv"
            else:
                fmt = "csv"

        # Generate auto-named file path now that format is known
        if auto_name:
            server_name = urlparse(client.host).hostname or re.sub(
                r"[^\w.-]", "_", client.host
            )
            ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            ext = (
                ".feather"
                if fmt == "feather"
                else ".json"
                if fmt in ("json", "raw")
                else ".csv"
            )
            output = f"signalk-history-{server_name}-{ts}{ext}"

        out_file = None if output is None or output == "-" else output
        write_to_stdout = out_file is None
        write_to_file = not write_to_stdout

        if fmt == "feather" and write_to_stdout:
            raise click.UsageError(
                "feather cannot be written to stdout (binary format); "
                "use --output FILE or --output to auto-name"
            )

        click.echo(f"Server:      {client.host}", err=True)
        click.echo(f"Provider:    {client.provider or '(none)'}", err=True)
        click.echo(f"Context:     {context}", err=True)
        _echo_time(time_params, 13)
        click.echo(f"Resolution:  {resolution or '(server default)'}", err=True)
        click.echo(f"Format:      {fmt}", err=True)

        with _exit_on_error("resolving paths"):
            resolved = client.expand_paths(list(paths), time)

        if not resolved:
            click.echo("No paths matched — nothing to query.", err=True)
            sys.exit(1)

        params, wide_mode = client.value_params(
            resolved,
            time,
            aggregation=aggregation,
            samples=samples,
            alpha=alpha,
            resolution=resolution,
            expand=False,
        )
        agg_label = aggregation or ("wide (min/max/average)" if wide_mode else "inline")
        click.echo(f"Aggregation: {agg_label}", err=True)

        # raw + stdout + no pretty: stream response bytes directly
        if fmt == "raw" and write_to_stdout and not pretty:
            with (
                _exit_on_error("fetching history"),
                client.fetch("values", params, stream=True) as resp,
            ):
                for chunk in resp.iter_content(chunk_size=65536, decode_unicode=True):
                    sys.stdout.write(chunk)
            sys.stdout.write("\n")
            return

        with _exit_on_error("fetching history"):
            resp = client.fetch("values", params)

        indent = 2 if pretty else None

        if fmt == "feather" and out_file is not None:
            table = HistoryResult(resp.json(), wide=wide_mode).to_arrow()
            write_feather(table, out_file)
            click.echo(f"Wrote {output}", err=True)
            click.echo(_summary(table.to_pydict()["path"], table.num_rows), err=True)
            return

        if fmt == "raw":
            text = (
                json.dumps(resp.json(), indent=indent) if pretty else (resp.text or "")
            )
            if out_file is not None:
                Path(out_file).write_text(text)
                click.echo(f"Wrote {output}", err=True)
            else:
                sys.stdout.write(text + "\n")
            return

        result = resp.json()
        with (
            open(out_file, "w", newline="")
            if out_file is not None
            else contextlib.nullcontext(sys.stdout)
        ) as sink:
            if fmt == "json":
                writer = write_json_wide if wide_mode else write_json
                row_count, unique_paths = writer(result, sink, indent=indent)
                if not write_to_file:
                    sink.write("\n")
            else:
                csv_writer = write_csv_wide if wide_mode else write_csv
                row_count, unique_paths = csv_writer(result, sink, no_header)
        if write_to_file:
            click.echo(f"Wrote {output}", err=True)
        click.echo(_summary(unique_paths, row_count), err=True)


# ---------------------------------------------------------------------------
# cardinality
# ---------------------------------------------------------------------------


@cli.command()
@click.argument("paths", nargs=-1, required=False, metavar="PATH...")
@_host_option
@_time_options
@click.option(
    "--resolution",
    metavar="RESOLUTION",
    help="Sample window: integer seconds or time expression (1s, 1m, 1h, 1d)",
)
@click.option(
    "--context", "-c", default="vessels.self", show_default=True, help="SignalK context"
)
@_provider_options
@click.option(
    "--format",
    "fmt",
    metavar="[csv|json]",
    default="csv",
    callback=_list_fmt_callback,
    help="Output format: csv or json",
)
@click.option("--no-header", is_flag=True, help="Suppress header row (CSV only)")
@_bare_option
def cardinality(
    paths: tuple[str, ...],
    host: str | None,
    from_: str | None,
    to: str | None,
    duration: str | None,
    resolution: str | None,
    context: str,
    provider: str | None,
    no_cache: bool,
    fmt: str,
    no_header: bool,
    bare: bool,
) -> None:
    """Compute per-path value statistics for the given time range.

    Outputs a table of: path, distinct_values, min, max, average,
    distinct_values_2_decimal_places, nulls.

    For non-scalar values (e.g. navigation.position) min/max/average and
    distinct_values_2_decimal_places are left blank.

    \b
    Examples:
      signalk_cli.history cardinality --host 10.36.10.21 --duration PT1H navigation.speedOverGround
      signalk_cli.history cardinality --host 10.36.10.21 --duration PT1H '*'
    """
    with _stderr_ctx(bare):
        client = _client(host, provider, no_cache, context)
        time = TimeRange(from_, to, duration).resolved()

        click.echo(f"Server:      {client.host}", err=True)
        click.echo(f"Provider:    {client.provider or '(none)'}", err=True)
        click.echo(f"Context:     {context}", err=True)
        _echo_time(time.params(), 13)
        click.echo(f"Resolution:  {resolution or '(server default)'}", err=True)

        with _exit_on_error("resolving paths"):
            resolved = client.expand_paths(list(paths) or ["*"], time)

        if not resolved:
            click.echo("No paths matched — nothing to query.", err=True)
            sys.exit(1)

        with _exit_on_error("fetching history"):
            stat_rows = [
                cardinality_text(r)
                for r in client.cardinality_rows(resolved, time, resolution=resolution)
            ]

        if fmt == "json":
            click.echo(json.dumps(stat_rows, indent=2))
        else:
            writer = csv.writer(sys.stdout)
            if not no_header:
                writer.writerow(CARDINALITY_COLUMNS)
            for row in stat_rows:
                writer.writerow([row[col] for col in CARDINALITY_COLUMNS])

        click.echo(f"{len(stat_rows)} path(s)", err=True)


# ---------------------------------------------------------------------------
# list-paths
# ---------------------------------------------------------------------------


@cli.command("list-paths")
@_host_option
@_time_options
@_provider_options
@click.option(
    "--context", "-c", default="vessels.self", show_default=True, help="SignalK context"
)
@click.option(
    "--format",
    "fmt",
    metavar="[csv|json|raw]",
    default="csv",
    callback=_list_fmt_callback,
    help="Output format: csv (one item per line), json (re-serialized), or raw (exact API response body). Feather is only available on `query` (requires signalk-cli[feather]).",
)
@_bare_option
def list_paths(
    host: str | None,
    from_: str | None,
    to: str | None,
    duration: str | None,
    provider: str | None,
    no_cache: bool,
    context: str,
    fmt: str,
    bare: bool,
) -> None:
    """List paths that have data for the given time range."""
    with _stderr_ctx(bare):
        client = _client(host, provider, no_cache, context)
        time = TimeRange(from_, to, duration).resolved()

        click.echo(f"Server:   {client.host}", err=True)
        click.echo(f"Provider: {client.provider or '(none)'}", err=True)
        _echo_time(time.params(), 10)

        with _exit_on_error("fetching paths"):
            if fmt == "raw":
                click.echo(client.fetch("paths", client.request_params(time)).text)
                return
            paths = client.paths(time)
        if fmt == "json":
            click.echo(json.dumps([{"path": p} for p in paths]))
        else:
            click.echo("path")
            for path in paths:
                click.echo(path)
            click.echo(f"{len(paths)} path(s)", err=True)


# ---------------------------------------------------------------------------
# list-providers
# ---------------------------------------------------------------------------


@cli.command("list-providers")
@_host_option
@click.option(
    "--format",
    "fmt",
    metavar="[csv|json|raw]",
    default="csv",
    callback=_list_fmt_callback,
    help="Output format: csv (one item per line), json (re-serialized), or raw (exact API response body). Feather is only available on `query` (requires signalk-cli[feather]).",
)
@_bare_option
def list_providers(host: str | None, fmt: str, bare: bool) -> None:
    """List registered history providers."""
    with _stderr_ctx(bare):
        client = _client(host)
        click.echo(f"Server: {client.host}", err=True)

        with _exit_on_error("fetching providers"):
            if fmt == "raw":
                click.echo(client.fetch("_providers").text)
                return
            providers = client.providers()

        if fmt == "json":
            rows = [
                {"provider": pid, **info} for pid, info in sorted(providers.items())
            ]
            click.echo(json.dumps(rows))
        else:
            writer = csv.writer(sys.stdout)
            writer.writerow(["provider", "isDefault"])
            for pid, info in sorted(providers.items()):
                writer.writerow([pid, info.get("isDefault", False)])
            click.echo(f"{len(providers)} provider(s)", err=True)


# ---------------------------------------------------------------------------
# list-contexts
# ---------------------------------------------------------------------------


@cli.command("list-contexts")
@_host_option
@_time_options
@_provider_options
@click.option(
    "--format",
    "fmt",
    metavar="[csv|json|raw]",
    default="csv",
    callback=_list_fmt_callback,
    help="Output format: csv (one item per line), json (re-serialized), or raw (exact API response body). Feather is only available on `query` (requires signalk-cli[feather]).",
)
@_bare_option
def list_contexts(
    host: str | None,
    from_: str | None,
    to: str | None,
    duration: str | None,
    provider: str | None,
    no_cache: bool,
    fmt: str,
    bare: bool,
) -> None:
    """List contexts that have historical data for the given time range."""
    with _stderr_ctx(bare):
        client = _client(host, provider, no_cache)
        time = TimeRange(from_, to, duration).resolved()

        click.echo(f"Server:   {client.host}", err=True)
        click.echo(f"Provider: {client.provider or '(none)'}", err=True)
        _echo_time(time.params(), 10)

        with _exit_on_error("fetching contexts"):
            if fmt == "raw":
                click.echo(client.fetch("contexts", client.request_params(time)).text)
                return
            contexts = client.contexts(time)

        if fmt == "json":
            click.echo(json.dumps([{"context": c} for c in contexts]))
        else:
            click.echo("context")
            for ctx in contexts:
                click.echo(ctx)
            click.echo(f"{len(contexts)} context(s)", err=True)
