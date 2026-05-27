# SignalK CLI

Query and explore SignalK APIs from the command line and export data as CSV or Apache Arrow Feather. Presently the [SignalK v2 History API](https://signalk.org/https://demo.signalk.org/documentation/Developing/REST_APIs/History_API.html) is supported.

## Installation

### PyPi

```pip install signalk-cli``` or ```uv pip install signalk-cli```

### Local Copy

Requires Python 3.13+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone <repo>
cd signalk-history-cli
uv sync
```

## Commands

Run via `uv run history.py <command>`. Set `SIGNALK_HOST` to avoid repeating `--host` on every call.

```bash
export SIGNALK_HOST=10.36.10.21   # http:// is added automatically if omitted
```

Run with no arguments to list available commands:

```
$ uv run history.py
Usage: history.py [OPTIONS] COMMAND [ARGS]...

  SignalK v2 history CLI.

Commands:
  list-contexts   List contexts that have historical data for the given time range.
  list-paths      List paths that have data for the given time range.
  list-providers  List registered history providers.
  query           Query history and write results as CSV or Feather.
```

---

### `query`

Fetch historical values for one or more paths and write to a file (default) or stdout. Aggregation can be controlled in the same way as the History API itself
or a default form where `min_value`,`avg_value` and `max_value` are returned for every period.

```
uv run history.py query [OPTIONS] PATH...
```

**PATH** arguments may be:
- **Literal paths** — e.g. `navigation.speedOverGround`
- **Regex / glob patterns** — any argument containing metacharacters (`*`, `.`, `[`, `(`, etc.) is matched against the server's `/paths` endpoint. Bare `*` is treated as a glob wildcard.
- **Inline path specs** — `path:method` or `path:method:param`, e.g. `navigation.speedOverGround:sma:5`. These pass through to the server unchanged.

#### Options

| Option | Default | Description |
|---|---|---|
| `--host` | `$SIGNALK_HOST` | Server base URL. `http://` added if scheme omitted. |
| `--from DATETIME` | — | Start of range (ISO 8601, e.g. `2026-05-26T00:00:00Z`) |
| `--to DATETIME` | now | End of range (ISO 8601) |
| `--duration DURATION` | — | Duration as seconds (`3600`) or ISO 8601 (`PT1H`, `PT15M`). Combined with `--from` or `--to`, or alone for a window ending now. |
| `--resolution RESOLUTION` | server default | Sample window size: seconds or time expression (`1s`, `1m`, `1h`, `1d`). |
| `-c, --context TEXT` | `vessels.self` | SignalK context |
| `--provider TEXT` | fetched & cached | History provider plugin id |
| `--no-cache` | — | Ignore the cached default provider |
| `--aggregation / --agg` | — | Aggregation method: `average`, `min`, `max`, `first`, `last`, `mid`, `middle_index`, `sma`, `ema`. Omit for wide mode (see below). |
| `--samples N` | server default | Sample count for `--agg sma` |
| `--alpha FLOAT` | server default | Alpha (0–1) for `--agg ema` |
| `--format [csv\|feather]` | from extension, else csv | Output format. Auto-detected from `.feather`, `.arrow`, `.fea` extensions. |
| `--no-header` | — | Suppress the CSV header row |
| `-o / --output FILE` | auto-named | Output file. Use `-` to write CSV to stdout. |
| `--stdout` | — | Print CSV to stdout. If `--output` is also given, writes to both. Not supported with feather. |

Output files are auto-named `signalk-history-<server>-<timestamp>.<ext>` in the current directory.

If no time range is given, the tool defaults to the hour ending now.

#### Output columns

**Wide mode** (default — no `--aggregation` and no inline specs): fetches `min`, `average`, and `max` for each path and writes them as separate columns:

```
timestamp, path, min_value, avg_value, max_value
```

**Narrow mode** (explicit `--aggregation` or inline path specs): single value column:

```
timestamp, path, value
```

Structured values (positions, arrays) are JSON-encoded in the value column.

Feather output produces the same columns as Apache Arrow Feather, readable with pandas, Polars, R, pyarrow, etc.

#### Examples

```bash
# Last hour of speed — wide mode (min/max/avg columns), auto-named CSV
uv run history.py query --host 10.36.10.21 --duration PT1H \
    navigation.speedOverGround

# Wide mode printed to stdout
uv run history.py query --host 10.36.10.21 --duration PT1H --stdout \
    navigation.speedOverGround

# Simple moving average (5 samples), narrowed to one value column
uv run history.py query --host 10.36.10.21 --duration PT1H \
    --agg sma --samples 5 \
    navigation.speedOverGround

# EMA with alpha 0.2
uv run history.py query --host 10.36.10.21 --duration PT1H \
    --agg ema --alpha 0.2 \
    navigation.speedOverGround

# Inline spec — path:method, multiple paths with different methods
uv run history.py query --host 10.36.10.21 --duration PT1H --stdout \
    'navigation.speedOverGround:max' 'navigation.courseOverGroundTrue:average'

# Multiple literal paths, 1-minute resolution
uv run history.py query --host 10.36.10.21 --duration PT1H --resolution 1m \
    navigation.speedOverGround navigation.courseOverGroundTrue

# All navigation paths, specific date range, write to named file
uv run history.py query --host 10.36.10.21 \
    --from 2026-05-26T00:00:00Z --to 2026-05-27T00:00:00Z \
    --output may26.csv \
    'navigation\..*'

# Glob wildcard — all paths for the last 30 minutes as Feather
uv run history.py query --host 10.36.10.21 --duration PT30M --format feather '*'

# Extension auto-selects feather format
uv run history.py query --host 10.36.10.21 --duration PT1H \
    -o out.feather navigation.speedOverGround

# Write to both a file and stdout
uv run history.py query --host 10.36.10.21 --duration PT1H \
    --output out.csv --stdout navigation.speedOverGround

# Duration in seconds, suppress header, pipe to another tool
uv run history.py query --host 10.36.10.21 --duration 3600 --no-header --stdout \
    navigation.speedOverGround | cut -d, -f1,3

# Different context
uv run history.py query --host 10.36.10.21 --duration PT1H -c vessels.urn:mrn:imo:mmsi:123456789 \
    navigation.speedOverGround
```

---

### `list-paths`

List all SignalK paths that have recorded data in a given time range.

```
uv run history.py list-paths [OPTIONS]
```

Outputs one path per line to stdout. Defaults to the last hour if no time range is given. Accepts the same `--from`/`--to`/`--duration`, `--provider`/`--no-cache`, and `-c/--context` options as `query`.

```bash
# Paths recorded in the last hour
uv run history.py list-paths --host 10.36.10.21

# Paths available on a specific day
uv run history.py list-paths --host 10.36.10.21 \
    --from 2026-05-26T00:00:00Z --to 2026-05-27T00:00:00Z

# Pipe into grep
uv run history.py list-paths --host 10.36.10.21 --duration PT24H | grep navigation
```

---

### `list-providers`

List all registered history provider plugins and identify the default.

```
uv run history.py list-providers --host 10.36.10.21
```

Example output:

```
kip (default)
signalk-parquet
2 provider(s)
```

The default provider is used automatically when `--provider` is not specified on other commands. It is fetched once and cached in `~/.cache/signalk-history-cli/`.

---

### `list-contexts`

List SignalK contexts (vessels, aircraft, etc.) that have recorded data in a given time range.

```
uv run history.py list-contexts [OPTIONS]
```

Defaults to the last hour if no time range is given.

```bash
uv run history.py list-contexts --host 10.36.10.21

uv run history.py list-contexts --host 10.36.10.21 \
    --from 2026-05-26T00:00:00Z --to 2026-05-27T00:00:00Z
```

---

## Time range

All commands that query data accept the same three time parameters. At least one of `--from` or `--duration` must be provided (or the tool supplies a one-hour default).

| Parameter | Format | Examples |
|---|---|---|
| `--from` | ISO 8601 timestamp | `2026-05-26T00:00:00Z` |
| `--to` | ISO 8601 timestamp | `2026-05-27T00:00:00Z` |
| `--duration` | ISO 8601 duration or integer seconds | `PT1H`, `PT15M`, `3600` |

Typical combinations:

- `--duration PT1H` — last hour ending now
- `--from T --duration PT1H` — hour starting at T
- `--from T1 --to T2` — explicit range
- `--duration PT1H --to T` — hour ending at T

## Provider caching

The default history provider is fetched from the server once and cached per host in `~/.cache/signalk-history-cli/`. Pass `--no-cache` to force a fresh lookup, or `--provider <id>` to target a specific provider explicitly.
