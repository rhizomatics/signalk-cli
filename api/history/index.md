# History API reference

Import from `signalk_cli.history` (or `signalk_cli` for the main classes).

Python API for the SignalK v2 History API.

Examples:

```python
from signalk_cli.history import HistoryClient, TimeRange
with HistoryClient("http://boat.local:3000") as client:
    table = client.query(["navigation.speedOverGround"], TimeRange(duration="PT1H"))
import polars as pl
df = pl.DataFrame(table)
```

## AGGREGATION_METHODS

```python
AGGREGATION_METHODS = (
    "average",
    "min",
    "max",
    "first",
    "last",
    "mid",
    "middle_index",
    "sma",
    "ema",
)
```

## HistoryClient

```python
HistoryClient(
    host: str,
    *,
    provider: str | None = None,
    context: str = "vessels.self",
    session: Session | None = None,
    cache: bool = False,
    timeout: float = 60,
)
```

Client for a SignalK server’s v2 History API.

Parameters:

- **`host`** (`str`) – Server URL, e.g. http://boat.local:3000 (http:// is added if there’s no scheme).
- **`provider`** (`str | None`, default: `None` ) – History provider plugin id. Defaults to the server’s default provider, looked up on first use.
- **`context`** (`str`, default: `'vessels.self'` ) – SignalK context to query, e.g. vessels.self.
- **`session`** (`Session | None`, default: `None` ) – A niquests session to send requests with. One is created (and closed with the client) if not given.
- **`cache`** (`bool`, default: `False` ) – Remember each server’s default provider on disk, under ~/.cache/signalk-cli, to save a request next time.
- **`timeout`** (`float`, default: `60` ) – Seconds to wait for each response.

Raises:

- `SignalKError` – From any method, when a request fails.

### provider

```python
provider: str | None
```

The provider used for requests: the one given, else the server’s default.

The default is fetched once (or read from the disk cache if enabled). If it can’t be fetched, requests go without one and the server picks.

### close

```python
close() -> None
```

Close the session, if the client created it.

### fetch

```python
fetch(
    endpoint: str,
    params: dict | None = None,
    *,
    stream: bool = False,
) -> niquests.Response
```

GET a History API endpoint (e.g. `"values"`, `"paths"`) and return the response.

A low-level escape hatch for callers that want the raw response body; the other methods are usually more convenient.

### providers

```python
providers() -> dict[str, dict[str, Any]]
```

Registered history providers, as `{id: {"isDefault": bool, ...}}`.

### default_provider

```python
default_provider() -> str
```

The id of the server’s default history provider.

### request_params

```python
request_params(
    time: TimeRange | None = None, **extra: Any
) -> dict[str, Any]
```

Query parameters for a request: the time range, provider, and any extras given.

Useful with fetch(); `None` extras are left out.

### contexts

```python
contexts(time: TimeRange | None = None) -> list[str]
```

Contexts (vessels, aircraft, …) with data in the time range, sorted.

### paths

```python
paths(time: TimeRange | None = None) -> list[str]
```

Paths with data in the time range, sorted.

### expand_paths

```python
expand_paths(
    patterns: Sequence[str], time: TimeRange | None = None
) -> list[str]
```

Expand glob/regex patterns to the matching paths with data in the time range.

Only fetches the server’s path list if there’s a pattern to match. See match_paths() for the matching rules.

### value_params

```python
value_params(
    paths: Sequence[str],
    time: TimeRange | None = None,
    *,
    aggregation: str | None = None,
    samples: int | None = None,
    alpha: float | None = None,
    resolution: str | int | None = None,
    context: str | None = None,
    expand: bool = True,
) -> tuple[dict[str, Any], bool]
```

The query parameters values() sends, and whether the result is wide.

Useful with fetch() to get the raw response body. Arguments are as for values().

### values

```python
values(
    paths: Sequence[str],
    time: TimeRange | None = None,
    *,
    aggregation: str | None = None,
    samples: int | None = None,
    alpha: float | None = None,
    resolution: str | int | None = None,
    context: str | None = None,
    expand: bool = True,
) -> HistoryResult
```

Fetch values for the given paths, as a HistoryResult.

Parameters:

- **`paths`** (`Sequence[str]`) – Paths, glob/regex patterns, or inline specs such as navigation.speedOverGround:sma:5.
- **`time`** (`TimeRange | None`, default: `None` ) – Time range; defaults to the last hour.
- **`aggregation`** (`str | None`, default: `None` ) – Method applied to each path without an inline spec, one of AGGREGATION_METHODS. If neither this nor inline specs are given, min/average/max are fetched (wide).
- **`samples`** (`int | None`, default: `None` ) – Window size for sma.
- **`alpha`** (`float | None`, default: `None` ) – Smoothing factor for ema.
- **`resolution`** (`str | int | None`, default: `None` ) – Sample window, as seconds or an expression like 1m.
- **`context`** (`str | None`, default: `None` ) – Overrides the client’s context for this request.
- **`expand`** (`bool`, default: `True` ) – Expand patterns in paths first (see expand_paths()).

Raises:

- `ValueError` – If no paths are left to query after expansion.

### query

```python
query(
    paths: Sequence[str],
    time: TimeRange | None = None,
    *,
    shape: Shape | None = None,
    aggregation: str | None = None,
    samples: int | None = None,
    alpha: float | None = None,
    resolution: str | int | None = None,
    context: str | None = None,
) -> ArrowTable
```

Fetch values as a table for polars, pandas, pyarrow, DuckDB, etc.

Both shapes have one row per timestamp and path, with a UTC `timestamp` column and a `path` column:

- **long**: a single `value` column. It’s float64 if every value is a number, otherwise text, with objects and arrays as JSON.
- **wide**: `min_value`/`avg_value`/`max_value` for number paths, and one column per element for array paths (`longitude`/`latitude` for positions, otherwise `value_0`, `value_1`, …).

Warning

Wide column names may change in a future release.

The other arguments are as for values().

Parameters:

- **`shape`** (`Shape | None`, default: `None` ) – Defaults to wide if no aggregation or inline spec is given (min/average/max are fetched), otherwise long.

### cardinality

```python
cardinality(
    paths: Sequence[str] = ("*",),
    time: TimeRange | None = None,
    *,
    resolution: str | int | None = None,
    context: str | None = None,
) -> ArrowTable
```

Per-path statistics over the time range, as a table.

Columns: `path`, `distinct_values`, `distinct_values_2_decimal_places`, `nulls`, `zeroes`, `min`, `max`, `average`. `min`/`max`/`average` are null unless every value of the path is a number.

### cardinality_rows

```python
cardinality_rows(
    paths: Sequence[str] = ("*",),
    time: TimeRange | None = None,
    *,
    resolution: str | int | None = None,
    context: str | None = None,
) -> list[dict[str, Any]]
```

Like cardinality(), as a list of dicts.

## HistoryResult

```python
HistoryResult(payload: dict, *, wide: bool = False)
```

A /values response, with conversions to tables and statistics.

Attributes:

- **`payload`** – The decoded JSON response, as the server sent it.
- **`wide`** – True when the request asked for min/average/max per path, so the result reads naturally in the wide shape.

### paths

```python
paths: list[str]
```

Distinct paths in the response, in the order the server listed them.

### to_arrow

```python
to_arrow(shape: Shape | None = None) -> ArrowTable
```

Convert to a table; see query() for the two shapes.

Parameters:

- **`shape`** (`Shape | None`, default: `None` ) – "long" or "wide". Defaults to wide when the request asked for min/average/max, otherwise long.

### cardinality

```python
cardinality() -> list[dict[str, Any]]
```

Per-path statistics; see cardinality().

## build_path_specs

```python
build_path_specs(
    paths: Sequence[str],
    aggregation: str | None = None,
    samples: int | None = None,
    alpha: float | None = None,
) -> tuple[str, bool]
```

Build the `paths` query parameter, with an aggregation method per path.

Paths that already carry a method (`navigation.speedOverGround:sma:5`) pass through unchanged. With no aggregation and no inline methods, each path is requested as min, average and max (wide shape), except position paths, which don’t support those and are requested with `mid`.

Returns:

- `str` – (paths_param, wide), where wide says the response should be
- `bool` – read in the wide shape.

## match_paths

```python
match_paths(
    patterns: Sequence[str], available: Sequence[str]
) -> list[str]
```

Expand path patterns against a list of known paths.

Literal paths and inline specs (`path:method`) pass through unchanged. A path is a pattern if it contains any of `* ? + [ ] ( ) { } | ^ $ \` (a `.` alone doesn’t count, so `navigation.speedOverGround` is literal). Patterns are matched as globs (`navigation.*`) when they only use glob characters, otherwise as Python regular expressions (searched, not anchored); an invalid regex falls back to a glob.

Returns:

- `list[str]` – The literal paths in the order given, followed by all matched paths, sorted.

## TimeRange

```python
TimeRange(
    start: str | datetime | None = None,
    end: str | datetime | None = None,
    duration: str | int | timedelta | None = None,
)
```

The time window for a History API request.

Any combination of start, end and duration may be given, as the History API allows. Timestamps may be ISO 8601 strings or datetimes (naive datetimes are taken as UTC). Durations may be ISO 8601 strings (PT15M, P1D), integer seconds, or timedeltas.

Examples:

```python
last_hour = TimeRange(duration="PT1H")
one_day = TimeRange(start="2026-05-27T00:00:00Z", duration="P1D")
```

### resolved

```python
resolved() -> TimeRange
```

Return an equivalent range the server accepts, with all values as strings.

The server only accepts time-only durations (PT…), so durations with date parts (P1D, P1W) are expanded to explicit start and end timestamps. With no start and no duration, the range defaults to the hour ending at end, or now.

### params

```python
params() -> dict[str, str]
```

Return the from/to/duration query parameters for this range, as given.
