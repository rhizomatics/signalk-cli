"""Click CLI for the SignalK v1 Streaming (delta) API."""

import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import click
import niquests

from ..net import api_error, bare_option, host_option, resolve_host, stderr_ctx
from .output import (
    FEATHER_EXTENSIONS,
    extract_delta_rows,
    write_csv_delta,
    write_csv_header,
    write_feather_rows,
    write_json_delta,
)
from .stream_api import (
    SUBSCRIBE_POLICIES,
    SUBSCRIPTION_POLICIES,
    build_subscribe_message,
    iter_deltas,
    open_stream,
)

_AUTO_OUTPUT = "__auto_output__"

# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
def cli():
    """SignalK v1 streaming (delta) CLI."""


# ---------------------------------------------------------------------------
# deltas
# ---------------------------------------------------------------------------


@cli.command()
@click.argument("paths", nargs=-1, required=False, metavar="PATH...")
@host_option
@click.option("--no-cache", is_flag=True, help="Ignore cached host")
@click.option(
    "--context",
    "-c",
    default="vessels.self",
    show_default=True,
    help="SignalK context for the explicit subscription this command "
    "always sends. Also accepts the SignalK wildcard '*' (or 'vessels.*') "
    "to subscribe to every vessel at your own --policy/--period — the "
    "alternative to --subscribe all, which uses the server's default rate.",
)
@click.option(
    "--subscribe",
    type=click.Choice(SUBSCRIBE_POLICIES, case_sensitive=False),
    default="none",
    show_default=True,
    help="Connection-level auto-subscribe at the server's OWN default "
    "policy/period — separate from, and in addition to, this command's "
    "explicit --context subscription above. Defaults to 'none' (the "
    "SignalK spec's own default is 'self') to avoid double-subscribing "
    "your own context. 'all' adds other vessels at the server's rate; for "
    "other vessels at your chosen rate, use --context '*' instead.",
)
@click.option(
    "--policy",
    type=click.Choice(SUBSCRIPTION_POLICIES, case_sensitive=False),
    default="ideal",
    show_default=True,
    help="Per-path subscribe policy (SignalK Subscription Protocol 'policy' "
    "field): 'instant' sends every change, throttled by --min-period; "
    "'ideal' (default) behaves like instant but resends the last value if "
    "nothing changes within --period; 'fixed' always sends the last known "
    "value every --period regardless of changes.",
)
@click.option(
    "--period",
    type=float,
    default=60.0,
    show_default=True,
    metavar="SECONDS",
    help="Subscribe period in seconds — the resend interval used by the "
    "'ideal'/'fixed' policies. Converted to milliseconds on the wire.",
)
@click.option(
    "--min-period",
    "min_period",
    type=float,
    default=None,
    metavar="SECONDS",
    help="Fastest allowed transmission rate in seconds; only meaningful "
    "with --policy instant. Converted to milliseconds on the wire.",
)
@click.option(
    "--format",
    "fmt",
    default=None,
    type=click.Choice(["csv", "json", "raw", "feather"], case_sensitive=False),
    help="Output format (default: inferred from --output extension, else csv). "
    "json is JSON Lines (one row object per line). raw is the exact delta "
    "message text, one per line. feather requires "
    "pip install 'signalk-cli[feather]' and --output (cannot stream to stdout).",
)
@click.option("--no-header", is_flag=True, help="Suppress header row (CSV only)")
@click.option(
    "--include-meta",
    is_flag=True,
    help="Also emit rows for 'meta' entries (units, description, zones, etc.), "
    "not just 'values'. Adds a 'kind' column (value/meta) to csv/json/feather "
    "output. Ignored for --format raw, which always includes meta as-is.",
)
@click.option(
    "--output",
    "-o",
    is_flag=False,
    flag_value=_AUTO_OUTPUT,
    default=None,
    metavar="FILE",
    help="Write to FILE. Omit for stdout (default). Give without a filename to "
    "auto-name the file. Required for --format feather.",
)
@click.option(
    "--follow",
    "-f",
    is_flag=True,
    help="Keep streaming until interrupted (Ctrl-C) or --count is reached. "
    "Without this, print the next message then exit.",
)
@click.option(
    "--count",
    "-n",
    type=int,
    default=None,
    metavar="N",
    help="Number of delta messages to output. Default: 1 without --follow, "
    "unlimited with --follow.",
)
@bare_option
def deltas(
    paths,
    host,
    no_cache,
    context,
    subscribe,
    policy,
    period,
    min_period,
    fmt,
    no_header,
    include_meta,
    output,
    follow,
    count,
    bare,
):
    """Stream live delta updates from the SignalK v1 Streaming API.

    Connects via WebSocket and prints delta messages as they arrive, in
    csv, json (JSON Lines), raw, or Feather format.

    Always sends an explicit subscribe message for --context, covering
    PATH arguments if given, otherwise every path ('*'). PATH arguments
    are sent verbatim to the server, one per path. They may be literal
    SignalK paths (e.g. navigation.speedOverGround) or contain the
    SignalK subscription wildcard '*', matched server-side per the
    Subscription Protocol: '*' at the end of a path matches any suffix
    (navigation.*), and '*' as a middle segment matches any single
    segment there (propulsion.*.oilTemperature). Quote wildcarded paths
    to stop the shell expanding them. --policy/--period/--min-period
    control how that subscription behaves; --subscribe only controls
    whether the connection *additionally* auto-subscribes at the
    server's own default policy.

    \b
    Examples:
      # Next update for one path, then exit
      signalk_cli.stream deltas --host 10.36.10.21 navigation.speedOverGround

      # Tail all navigation updates every 5s until Ctrl-C
      signalk_cli.stream deltas --host 10.36.10.21 --follow --period 5 'navigation.*'

      # Tail oil temperature across every engine, sent instantly on change
      signalk_cli.stream deltas --host 10.36.10.21 --follow --policy instant \\
          'propulsion.*.oilTemperature'

      # Next 20 messages across all paths, as JSON Lines
      signalk_cli.stream deltas --host 10.36.10.21 --format json --count 20

      # Capture 100 messages to a Feather file (requires signalk-cli[feather])
      signalk_cli.stream deltas --host 10.36.10.21 --count 100 -o capture.feather
    """
    with stderr_ctx(bare):
        host = resolve_host(host, no_cache)
        period_ms = int(period * 1000)
        min_period_ms = int(min_period * 1000) if min_period is not None else None

        auto_name = output == _AUTO_OUTPUT

        if fmt is None:
            if output and not auto_name and output != "-":
                suffix = Path(output).suffix.lower()
                if suffix in FEATHER_EXTENSIONS:
                    fmt = "feather"
                elif suffix == ".json":
                    fmt = "json"
                else:
                    fmt = "csv"
            else:
                fmt = "csv"

        if auto_name:
            server_name = urlparse(host).hostname or re.sub(r"[^\w.-]", "_", host)
            ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            ext = (
                ".feather"
                if fmt == "feather"
                else ".json"
                if fmt in ("json", "raw")
                else ".csv"
            )
            output = f"signalk-stream-{server_name}-{ts}{ext}"

        write_to_stdout = output is None or output == "-"
        write_to_file = not write_to_stdout

        if fmt == "feather" and write_to_stdout:
            raise click.UsageError(
                "feather cannot be written to stdout (binary format); "
                "use --output FILE or --output to auto-name"
            )

        click.echo(f"Server:      {host}", err=True)
        click.echo(f"Context:     {context}", err=True)
        click.echo(f"Subscribe:   {subscribe}", err=True)
        min_period_note = (
            f", min_period={min_period}s" if min_period is not None else ""
        )
        click.echo(
            f"Policy:      {policy} (period={period}s{min_period_note})", err=True
        )
        click.echo(f"Format:      {fmt}", err=True)

        try:
            ws = open_stream(host, subscribe, timeout=None if follow else 30)
        except niquests.RequestException as e:
            click.echo(f"Error connecting to stream: {api_error(e)}", err=True)
            sys.exit(1)

        subscribe_message = build_subscribe_message(
            context,
            list(paths),
            period_ms=period_ms,
            policy=policy,
            min_period_ms=min_period_ms,
        )
        ws.send_payload(json.dumps(subscribe_message))

        effective_count = count if count is not None else (None if follow else 1)

        message_count = 0
        row_total = 0
        header_written = False
        feather_rows: list[tuple[str, ...]] = []
        fh = (
            open(output, "w", newline="")  # noqa: SIM115
            if write_to_file and fmt != "feather"
            else None
        )
        sink = fh or sys.stdout
        try:
            for raw, delta in iter_deltas(ws, effective_count):
                message_count += 1
                if fmt == "feather":
                    feather_rows.extend(
                        extract_delta_rows(delta, include_meta=include_meta)
                    )
                    row_total = len(feather_rows)
                elif fmt == "raw":
                    click.echo(raw, file=sink)
                elif fmt == "json":
                    row_total += write_json_delta(
                        delta, sink, include_meta=include_meta
                    )
                else:
                    if not header_written and not no_header:
                        write_csv_header(sink, include_meta=include_meta)
                        header_written = True
                    row_total += write_csv_delta(delta, sink, include_meta=include_meta)
        except KeyboardInterrupt:
            pass
        except niquests.RequestException as e:
            click.echo(f"Stream connection lost: {api_error(e)}", err=True)
        finally:
            ws.close()
            if fh:
                fh.close()

        if fmt == "feather":
            write_feather_rows(feather_rows, output, include_meta=include_meta)

        if write_to_file:
            click.echo(f"Wrote {output}", err=True)

        if fmt == "raw":
            click.echo(f"{message_count} message(s)", err=True)
        else:
            click.echo(f"{message_count} message(s), {row_total} row(s)", err=True)
