"""Click CLI for the SignalK v2 History API."""

import contextlib
import csv
import io
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import click
import niquests

from .history_api import (
    HISTORY_BASE,
    api_error,
    apply_time_default,
    discover_host,
    expand_paths,
    fetch_server_paths,
    get_cached_host,
    normalise_duration,
    normalise_host,
    resolve_provider,
    save_cached_host,
)
from .output import (
    CARDINALITY_COLUMNS,
    FEATHER_EXTENSIONS,
    _POSITION_RE,
    compute_cardinality,
    write_csv,
    write_csv_wide,
    write_feather,
    write_feather_wide,
    write_json,
    write_json_wide,
)

_AUTO_OUTPUT = "__auto_output__"

AGGREGATION_METHODS = [
    "average",
    "min",
    "max",
    "first",
    "last",
    "mid",
    "middle_index",
    "sma",
    "ema",
]

# ---------------------------------------------------------------------------
# Shared option decorators
# ---------------------------------------------------------------------------


def _list_fmt_callback(ctx, param, value):
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


def _host_option(f):
    return click.option(
        "--host",
        default=None,
        envvar="SIGNALK_HOST",
        help="SignalK server base URL. http:// added if scheme omitted. "
        "Discovered via mDNS if omitted.",
    )(f)


def _resolve_host(host: str | None, no_cache: bool = False) -> str:
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


def _provider_options(f):
    f = click.option("--no-cache", is_flag=True, help="Ignore cached default provider")(
        f
    )
    f = click.option(
        "--provider",
        help="History provider plugin id (default fetched and cached automatically)",
    )(f)
    return f


def _time_options(f):
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


def _bare_option(f):
    return click.option(
        "--bare",
        is_flag=True,
        help="Suppress all informational messages, outputting data only.",
    )(f)


def _stderr_ctx(bare: bool) -> contextlib.AbstractContextManager:
    return (
        contextlib.redirect_stderr(io.StringIO()) if bare else contextlib.nullcontext()
    )


def _build_time_params(from_: str | None, to: str | None, duration: str | None) -> dict:
    p: dict = {}
    if from_:
        p["from"] = from_
    if to:
        p["to"] = to
    if duration:
        p["duration"] = duration
    return p


def _build_path_specs(
    paths: list[str],
    aggregation: str | None,
    samples: int | None,
    alpha: float | None,
) -> tuple[str, bool]:
    """Build the comma-separated paths query param with aggregation suffixes.

    Returns (query_string, wide_mode).  wide_mode is True when no aggregation
    is given and no path contains an inline ':method' suffix — in that case
    min/max/average are requested and the output uses wide columns.
    """
    has_inline = any(":" in p for p in paths)

    if aggregation:
        specs = []
        for path in paths:
            if ":" in path:
                specs.append(path)  # inline spec passes through unchanged
            else:
                spec = f"{path}:{aggregation}"
                if aggregation == "sma" and samples is not None:
                    spec += f":{samples}"
                elif aggregation == "ema" and alpha is not None:
                    spec += f":{alpha}"
                specs.append(spec)
        return ",".join(specs), False

    if has_inline:
        return ",".join(paths), False

    # Default: wide mode.  Array-valued paths (e.g. navigation.position) don't
    # support min/average/max aggregation, so request a single passthrough method
    # instead; the output layer expands the array into named columns.
    specs = []
    for p in paths:
        if _POSITION_RE.fullmatch(p):
            specs.append(f"{p}:mid")
        else:
            for m in ("min", "average", "max"):
                specs.append(f"{p}:{m}")
    return ",".join(specs), True


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
    paths,
    host,
    from_,
    to,
    duration,
    resolution,
    context,
    provider,
    no_cache,
    aggregation,
    samples,
    alpha,
    fmt,
    no_header,
    output,
    pretty,
    bare,
):
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
        host = _resolve_host(host, no_cache)
        base_url = host.rstrip("/") + HISTORY_BASE
        provider = resolve_provider(host, base_url, provider, no_cache)

        # Normalise date-component durations (P1D etc.) to explicit from/to timestamps
        from_, to, duration = normalise_duration(duration, from_, to)
        time_params = apply_time_default(_build_time_params(from_, to, duration))

        # Determine output destination
        if output == _AUTO_OUTPUT:
            # Placeholder — filename generated after format is known
            auto_name = True
        else:
            auto_name = False

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
            server_name = urlparse(host).hostname or re.sub(r"[^\w.-]", "_", host)
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            ext = (
                ".feather"
                if fmt == "feather"
                else ".json"
                if fmt in ("json", "raw")
                else ".csv"
            )
            output = f"signalk-history-{server_name}-{ts}{ext}"

        write_to_stdout = output is None or output == "-"
        write_to_file = not write_to_stdout

        if fmt == "feather" and write_to_stdout:
            raise click.UsageError(
                "feather cannot be written to stdout (binary format); "
                "use --output FILE or --output to auto-name"
            )

        click.echo(f"Server:      {host}", err=True)
        click.echo(f"Provider:    {provider or '(none)'}", err=True)
        click.echo(f"Context:     {context}", err=True)
        click.echo(
            f"From:        {time_params.get('from', '(server default)')}", err=True
        )
        click.echo(
            f"To:          {time_params.get('to', '(server default)')}", err=True
        )
        click.echo(
            f"Duration:    {time_params.get('duration', '(not specified)')}", err=True
        )
        click.echo(f"Resolution:  {resolution or '(server default)'}", err=True)
        click.echo(f"Format:      {fmt}", err=True)

        try:
            resolved = expand_paths(list(paths), base_url, time_params, provider)
        except niquests.RequestException as e:
            click.echo(f"Error resolving paths: {api_error(e)}", err=True)
            sys.exit(1)

        if not resolved:
            click.echo("No paths matched — nothing to query.", err=True)
            sys.exit(1)

        path_query, wide_mode = _build_path_specs(resolved, aggregation, samples, alpha)
        agg_label = aggregation or ("wide (min/max/average)" if wide_mode else "inline")
        click.echo(f"Aggregation: {agg_label}", err=True)

        params: dict = {**time_params, "paths": path_query, "context": context}
        if resolution:
            params["resolution"] = resolution
        if provider:
            params["provider"] = provider

        url = f"{base_url}/values"

        # raw + stdout + no pretty: stream response bytes directly
        if fmt == "raw" and write_to_stdout and not pretty:
            try:
                with niquests.get(url, params=params, timeout=60, stream=True) as resp:
                    resp.raise_for_status()
                    for chunk in resp.iter_content(
                        chunk_size=65536, decode_unicode=True
                    ):
                        sys.stdout.write(chunk)
                sys.stdout.write("\n")
            except niquests.RequestException as e:
                click.echo(f"Error fetching history: {api_error(e)}", err=True)
                sys.exit(1)
            return

        try:
            resp = niquests.get(url, params=params, timeout=60)
            resp.raise_for_status()
        except niquests.RequestException as e:
            click.echo(f"Error fetching history: {api_error(e)}", err=True)
            sys.exit(1)

        indent = 2 if pretty else None

        def _open_sink():
            if write_to_file:
                return open(output, "w", newline="")
            return None

        if fmt == "feather":
            if wide_mode:
                row_count, unique_paths = write_feather_wide(resp.json(), output)
            else:
                row_count, unique_paths = write_feather(resp.json(), output)
            click.echo(f"Wrote {output}", err=True)
            click.echo(
                f"{row_count} rows, {len(unique_paths)} unique path(s): {', '.join(sorted(unique_paths))}",
                err=True,
            )

        elif fmt == "raw":
            raw_text = json.dumps(resp.json(), indent=indent) if pretty else resp.text
            fh = _open_sink()
            try:
                (fh or sys.stdout).write(raw_text)
                if not write_to_file:
                    sys.stdout.write("\n")
            finally:
                if fh:
                    fh.close()
            if write_to_file:
                click.echo(f"Wrote {output}", err=True)

        elif fmt == "json":
            result = resp.json()
            fh = _open_sink()
            try:
                sink = fh or sys.stdout
                if wide_mode:
                    row_count, unique_paths = write_json_wide(
                        result, sink, indent=indent
                    )
                else:
                    row_count, unique_paths = write_json(result, sink, indent=indent)
                if not write_to_file:
                    sys.stdout.write("\n")
            finally:
                if fh:
                    fh.close()
            if write_to_file:
                click.echo(f"Wrote {output}", err=True)
            click.echo(
                f"{row_count} rows, {len(unique_paths)} unique path(s): {', '.join(sorted(unique_paths))}",
                err=True,
            )

        else:  # csv
            result = resp.json()
            fh = _open_sink()
            try:
                sink = fh or sys.stdout
                if wide_mode:
                    row_count, unique_paths = write_csv_wide(result, sink, no_header)
                else:
                    row_count, unique_paths = write_csv(result, sink, no_header)
            finally:
                if fh:
                    fh.close()
            if write_to_file:
                click.echo(f"Wrote {output}", err=True)
            click.echo(
                f"{row_count} rows, {len(unique_paths)} unique path(s): {', '.join(sorted(unique_paths))}",
                err=True,
            )


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
    paths,
    host,
    from_,
    to,
    duration,
    resolution,
    context,
    provider,
    no_cache,
    fmt,
    no_header,
    bare,
):
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
        host = _resolve_host(host, no_cache)
        base_url = host.rstrip("/") + HISTORY_BASE
        provider = resolve_provider(host, base_url, provider, no_cache)

        from_, to, duration = normalise_duration(duration, from_, to)
        time_params = apply_time_default(_build_time_params(from_, to, duration))

        click.echo(f"Server:      {host}", err=True)
        click.echo(f"Provider:    {provider or '(none)'}", err=True)
        click.echo(f"Context:     {context}", err=True)
        click.echo(
            f"From:        {time_params.get('from', '(server default)')}", err=True
        )
        click.echo(
            f"To:          {time_params.get('to', '(server default)')}", err=True
        )
        click.echo(
            f"Duration:    {time_params.get('duration', '(not specified)')}", err=True
        )
        click.echo(f"Resolution:  {resolution or '(server default)'}", err=True)

        try:
            resolved = expand_paths(
                list(paths) or ["*"], base_url, time_params, provider
            )
        except niquests.RequestException as e:
            click.echo(f"Error resolving paths: {api_error(e)}", err=True)
            sys.exit(1)

        if not resolved:
            click.echo("No paths matched — nothing to query.", err=True)
            sys.exit(1)

        params: dict = {
            **time_params,
            "paths": ",".join(resolved),
            "context": context,
        }
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

        stat_rows = compute_cardinality(resp.json())

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
def list_paths(host, from_, to, duration, provider, no_cache, context, fmt, bare):
    """List paths that have data for the given time range."""
    with _stderr_ctx(bare):
        host = _resolve_host(host, no_cache)
        base_url = host.rstrip("/") + HISTORY_BASE
        provider = resolve_provider(host, base_url, provider, no_cache)
        time_params = apply_time_default(_build_time_params(from_, to, duration))

        click.echo(f"Server:   {host}", err=True)
        click.echo(f"Provider: {provider or '(none)'}", err=True)
        click.echo(f"From:     {time_params.get('from', '(server default)')}", err=True)
        click.echo(f"To:       {time_params.get('to', '(server default)')}", err=True)
        click.echo(
            f"Duration: {time_params.get('duration', '(not specified)')}", err=True
        )

        if fmt == "raw":
            params = {k: v for k, v in time_params.items() if v is not None}
            if provider:
                params["provider"] = provider
            try:
                resp = niquests.get(f"{base_url}/paths", params=params, timeout=30)
                resp.raise_for_status()
            except niquests.RequestException as e:
                click.echo(f"Error fetching paths: {api_error(e)}", err=True)
                sys.exit(1)
            click.echo(resp.text)
        else:
            try:
                paths = fetch_server_paths(base_url, time_params, provider)
            except niquests.RequestException as e:
                click.echo(f"Error fetching paths: {api_error(e)}", err=True)
                sys.exit(1)
            if fmt == "json":
                click.echo(json.dumps([{"path": p} for p in sorted(paths)]))
            else:
                click.echo("path")
                for path in sorted(paths):
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
def list_providers(host, fmt, bare):
    """List registered history providers."""
    with _stderr_ctx(bare):
        host = _resolve_host(host)
        base_url = host.rstrip("/") + HISTORY_BASE
        click.echo(f"Server: {host}", err=True)

        try:
            resp = niquests.get(f"{base_url}/_providers", timeout=10)
            resp.raise_for_status()
        except niquests.RequestException as e:
            click.echo(f"Error fetching providers: {api_error(e)}", err=True)
            sys.exit(1)

        if fmt == "raw":
            click.echo(resp.text)
        else:
            providers: dict = resp.json()
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
def list_contexts(host, from_, to, duration, provider, no_cache, fmt, bare):
    """List contexts that have historical data for the given time range."""
    with _stderr_ctx(bare):
        host = _resolve_host(host, no_cache)
        base_url = host.rstrip("/") + HISTORY_BASE
        provider = resolve_provider(host, base_url, provider, no_cache)
        time_params = apply_time_default(_build_time_params(from_, to, duration))

        click.echo(f"Server:   {host}", err=True)
        click.echo(f"Provider: {provider or '(none)'}", err=True)
        click.echo(f"From:     {time_params.get('from', '(server default)')}", err=True)
        click.echo(f"To:       {time_params.get('to', '(server default)')}", err=True)
        click.echo(
            f"Duration: {time_params.get('duration', '(not specified)')}", err=True
        )

        params = {**time_params}
        if provider:
            params["provider"] = provider

        try:
            resp = niquests.get(f"{base_url}/contexts", params=params, timeout=30)
            resp.raise_for_status()
        except niquests.RequestException as e:
            click.echo(f"Error fetching contexts: {api_error(e)}", err=True)
            sys.exit(1)

        if fmt == "raw":
            click.echo(resp.text)
        else:
            contexts: list = resp.json()
            if fmt == "json":
                click.echo(json.dumps([{"context": c} for c in sorted(contexts)]))
            else:
                click.echo("context")
                for ctx in sorted(contexts):
                    click.echo(ctx)
                click.echo(f"{len(contexts)} context(s)", err=True)
