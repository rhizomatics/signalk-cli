# SignalK CLI

Query and explore SignalK APIs from the command line, and export data as CSV, Apache Arrow Feather, or JSON.

APIs supported:

* [SignalK v2 History API](https://signalk.org/https://demo.signalk.org/documentation/Developing/REST_APIs/History_API.html)

## Installation

### PyPi

```pip install signalk-cli``` or ```uv pip install signalk-cli```

For Apache Arrow Feather export, use the optional dependency: ```pip install 'signalk-cli[feather]'```

### Local Copy

Requires Python 3.13+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/rhizomatics/signalk-cli
cd signalk-cli
uv sync
```

## Temporary Installation

Use `uv` to run without installing the module permanently, for example:

```bash
uv run --with signalk-cli signalk_cli.history list-providers
```

## Running

Run via `python -m signalk_cli.history <command>`. 

## Determining SignalK host name

If no host name is set as an argument, the CLI will look for a `SIGNALK_HOST` environment variable, and failing that attempt to automatically discover
the host using mDNS (aka Bonjour) and locally cached (see [Default Caching](#default-caching)).

```bash
export SIGNALK_HOST=192.168.6.99   # http:// is added automatically if omitted
```

## Help

Run with no arguments to list available commands:

```
$ python -m signalk_cli.history
Usage: signalk_cli.history [OPTIONS] COMMAND [ARGS]...

  SignalK v2 history CLI.

Commands:
  list-contexts   List contexts that have historical data for the given time range.
  list-paths      List paths that have data for the given time range.
  list-providers  List registered history providers.
  query           Query history and write results as CSV, Feather, or JSON.
```

## Commands


### `query`

Fetch historical values for one or more paths and write to stdout (default) or a file. Aggregation can be controlled in the same way as the History API itself
or a default form where `min_value`,`avg_value` and `max_value` are returned for every period.

```
python -m signalk_cli.history query [OPTIONS] PATH...
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
| `--duration DURATION` | — | Duration as seconds (`3600`) or ISO 8601 duration (`PT1H`, `P1D`, `P1W`). Combined with `--from` or `--to`, or alone for a window ending now. |
| `--resolution RESOLUTION` | server default | Sample window size: seconds or time expression (`1s`, `1m`, `1h`, `1d`). |
| `-c, --context TEXT` | `vessels.self` | SignalK context |
| `--provider TEXT` | fetched & cached | History provider plugin name, for example `signalk-parquet` |
| `--no-cache` | — | Ignore the cached default provider |
| `--aggregation / --agg` | — | Aggregation method: `average`, `min`, `max`, `first`, `last`, `mid`, `middle_index`, `sma`, `ema`. Omit for wide mode (see below). |
| `--samples N` | server default | Sample count for `--agg sma` |
| `--alpha FLOAT` | server default | Alpha (0–1) for `--agg ema` |
| `--format [csv\|feather\|json\|raw]` | from extension, else csv | Output format. Auto-detected from `.feather`/`.arrow`/`.fea` and `.json` extensions. `feather` requires `pip install 'signalk-cli[feather]'`. |
| `--no-header` | — | Suppress the CSV header row |
| `-o / --output [FILE]` | stdout | Write to a file. Omit the filename (`--output` alone) to auto-name as `signalk-history-<server>-<timestamp>.<ext>`. Use `-` for stdout explicitly. Feather cannot be written to stdout. |
| `--pretty` | — | Pretty-print JSON output with indentation. **Warning:** disables streaming; the full response is buffered in memory before writing. |
| `--bare` | — | Print to stdout with **no informational messages** (server, provider, progress, row count). Ideal for piping to other tools. Not supported with feather. |

If no time range is given, the tool defaults to the hour ending now.

#### Duration normalisation

SignalK only accepts time-only ISO 8601 durations (`PT1H`, `PT30M`, etc.). Durations with date components (`P1D`, `P1W`, `P1Y`, `P1M`) are automatically expanded to explicit `--from`/`--to` timestamps:

- `--duration P1D` alone → `from = now − 1 day`, `to = now`
- `--from T --duration P1D` → `to = T + 1 day`
- `--to T --duration P1W` → `from = T − 1 week`

Integer seconds (`3600`) are passed through unchanged.

#### Output formats

**csv** (default): tabular output as comma-separated values.

**feather**: Apache Arrow Feather binary format, readable with pandas, Polars, R, pyarrow, etc. Requires `pip install 'signalk-cli[feather]'`. Cannot be written to stdout.

**json**: tabular records as JSON objects — same columns as CSV, formatted as a JSON array. Extension `.json` auto-selects this format.

**raw**: exact API response body as received from the server — no Python JSON parse/re-serialize. Streamed directly to stdout unless `--pretty` is used.

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

#### Examples

```bash
# Last hour of speed — wide mode (min/max/avg columns), printed to stdout
python -m signalk_cli.history query --host 10.36.10.21 --duration PT1H \
    navigation.speedOverGround

# Write to auto-named file
python -m signalk_cli.history query --host 10.36.10.21 --duration PT1H --output \
    navigation.speedOverGround

# Write to named file
python -m signalk_cli.history query --host 10.36.10.21 --duration PT1H \
    --output may26.csv navigation.speedOverGround

# Last day (date-component duration, auto-expanded to from/to)
python -m signalk_cli.history query --host 10.36.10.21 --duration P1D \
    navigation.speedOverGround

# Simple moving average (5 samples), narrowed to one value column
python -m signalk_cli.history query --host 10.36.10.21 --duration PT1H \
    --agg sma --samples 5 \
    navigation.speedOverGround

# EMA with alpha 0.2
python -m signalk_cli.history query --host 10.36.10.21 --duration PT1H \
    --agg ema --alpha 0.2 \
    navigation.speedOverGround

# Inline spec — path:method, multiple paths with different methods
python -m signalk_cli.history query --host 10.36.10.21 --duration PT1H \
    'navigation.speedOverGround:max' 'navigation.courseOverGroundTrue:average'

# Multiple literal paths, 1-minute resolution
python -m signalk_cli.history query --host 10.36.10.21 --duration PT1H --resolution 1m \
    navigation.speedOverGround navigation.courseOverGroundTrue

# All navigation paths, specific date range, write to named file
python -m signalk_cli.history query --host 10.36.10.21 \
    --from 2026-05-26T00:00:00Z --to 2026-05-27T00:00:00Z \
    --output may26.csv \
    'navigation\..*'

# Glob wildcard — all paths for the last 30 minutes as Feather (auto-named)
python -m signalk_cli.history query --host 10.36.10.21 --duration PT30M \
    --format feather --output '*'

# Extension auto-selects feather format
python -m signalk_cli.history query --host 10.36.10.21 --duration PT1H \
    -o out.feather navigation.speedOverGround

# Exact API response body to stdout (streamed, no informational noise)
python -m signalk_cli.history query --host 10.36.10.21 --duration PT1H --format raw --bare \
    navigation.speedOverGround

# Pretty-printed raw JSON (buffered — avoid for large responses)
python -m signalk_cli.history query --host 10.36.10.21 --duration PT1H \
    --format raw --pretty navigation.speedOverGround

# Extension auto-selects JSON format
python -m signalk_cli.history query --host 10.36.10.21 --duration PT1H \
    -o out.json navigation.speedOverGround

# Suppress header, pipe to another tool
python -m signalk_cli.history query --host 10.36.10.21 --duration 3600 --no-header \
    navigation.speedOverGround | cut -d, -f1,3

# --bare: pure CSV output, no informational noise — pipe-friendly
python -m signalk_cli.history query --host 10.36.10.21 --duration PT1H --bare \
    navigation.speedOverGround | awk -F, 'NR>1 {print $2, $3}'

# Different context
python -m signalk_cli.history query --host 10.36.10.21 --duration PT1H \
    -c vessels.urn:mrn:imo:mmsi:123456789 navigation.speedOverGround
```

---

### `list-paths`

List all SignalK paths that have recorded data in a given time range.

```
python -m signalk_cli.history list-paths [OPTIONS]
```

Outputs one path per line to stdout by default. Defaults to the last hour if no time range is given. Accepts the same `--from`/`--to`/`--duration`, `--provider`/`--no-cache`, `-c/--context`, and `--bare` options as `query`.

#### Options

| Option | Default | Description |
|---|---|---|
| `--format [csv\|json\|raw]` | `csv` | `csv`: one item per line with `path` header. `json`: `[{"path": ...}]`. `raw`: exact API response body. |

```bash
# Paths recorded in the last hour
python -m signalk_cli.history list-paths --host 10.36.10.21

# Paths available on a specific day
python -m signalk_cli.history list-paths --host 10.36.10.21 \
    --from 2026-05-26T00:00:00Z --to 2026-05-27T00:00:00Z

# Pipe into grep
python -m signalk_cli.history list-paths --host 10.36.10.21 --duration PT24H | grep navigation

# Exact API response body, no informational noise
python -m signalk_cli.history list-paths --host 10.36.10.21 --format raw --bare
```

---

### `list-providers`

List all registered history provider plugins and identify the default. Supports `--bare` to suppress the "Server:" and provider-count lines.

```
python -m signalk_cli.history list-providers --host 10.36.10.21
```

Example output:

```
provider,isDefault
signalk-parquet,True
kip,False
2 provider(s)
```

The default provider is used automatically when `--provider` is not specified on other commands. It is fetched once and cached in `~/.cache/signalk-cli/`.

#### Options

| Option | Default | Description |
|---|---|---|
| `--format [csv\|json\|raw]` | `csv` | `csv`: `provider,isDefault` rows. `json`: `[{"provider": ..., "isDefault": ...}]`. `raw`: exact API response body. |

```bash
# Exact API response body, no informational noise
python -m signalk_cli.history list-providers --host 10.36.10.21 --format raw --bare
```

---

### `list-contexts`

List SignalK contexts (vessels, aircraft, etc.) that have recorded data in a given time range.

```bash
python -m signalk_cli.history list-contexts [OPTIONS]
```

Defaults to the last hour if no time range is given.

#### Options

| Option | Default | Description |
|---|---|---|
| `--format [csv\|json\|raw]` | `csv` | `csv`: one item per line with `context` header. `json`: `[{"context": ...}]`. `raw`: exact API response body. |

```bash
python -m signalk_cli.history list-contexts --host 10.36.10.21

python -m signalk_cli.history list-contexts --host 10.36.10.21 \
    --from 2026-05-26T00:00:00Z --to 2026-05-27T00:00:00Z

# Exact API response body, no informational noise
python -m signalk_cli.history list-contexts --host 10.36.10.21 --format raw --bare
```

---

## Time range

All commands that query data accept the same three time parameters. At least one of `--from` or `--duration` must be provided (or the tool supplies a one-hour default).

| Parameter | Format | Examples |
|---|---|---|
| `--from` | ISO 8601 timestamp | `2026-05-26T00:00:00Z` |
| `--to` | ISO 8601 timestamp | `2026-05-27T00:00:00Z` |
| `--duration` | ISO 8601 duration or integer seconds | `PT1H`, `PT15M`, `P1D`, `P1W`, `3600` |

Typical combinations:

- `--duration PT1H` — last hour ending now
- `--from T --duration PT1H` — hour starting at T
- `--from T1 --to T2` — explicit range
- `--duration PT1H --to T` — hour ending at T
- `--duration P1D` — last 24 hours (expanded to from/to automatically)

## Default caching

The default history provider is fetched from the server once and cached per host in `~/.cache/signalk-history-cli/`. Pass `--no-cache` to force a fresh lookup, or `--provider <id>` to target a specific provider explicitly.
