# Python library

Everything the CLI does is available from Python, for scripts, apps and notebooks (including [marimo](https://marimo.io) and Jupyter in the browser via Pyodide).

```bash
pip install signalk-cli
```

Queries return an ArrowTable, which loads directly into any Arrow-aware dataframe library through the [Arrow PyCapsule interface](https://arrow.apache.org/docs/format/CDataInterface/PyCapsuleInterface.html). signalk-cli itself only depends on the small `nanoarrow` package for this, not on pyarrow.

## History

```python
from signalk_cli import HistoryClient, TimeRange
import polars as pl

with HistoryClient("http://boat.local:3000") as client:
    print(client.paths(TimeRange(duration="P1D")))

    table = client.query(
        ["navigation.speedOverGround", "environment.wind.*"],
        TimeRange(duration="P1D"),
        resolution="5m",
    )

df = pl.DataFrame(table)
```

The same table works with other libraries:

```python
import pandas as pd

df = pd.DataFrame.from_arrow(table)  # pandas 3.0+
```

```python
import pyarrow as pa

t = pa.table(table)
```

```python
import duckdb

rel = duckdb.from_arrow(table)
duckdb.sql("select path, avg(avg_value) from rel group by path")
```

### Table shapes

Both shapes have one row per timestamp and path, with a UTC `timestamp` column and a `path` column.

| Shape    | When                                                                      | Value columns                                                                                                                     |
| -------- | ------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| **wide** | No aggregation given (the default)                                        | `min_value`, `avg_value`, `max_value` for numbers; `longitude`/`latitude` for positions; `value_0`, `value_1`, … for other arrays |
| **long** | An `aggregation`, or inline specs like `navigation.speedOverGround:sma:5` | `value`: float when every value is a number, otherwise text (objects and arrays as JSON)                                          |

Pass `shape="long"` or `shape="wide"` to query() to choose.

Wide column names may change

The wide shape’s column names aren’t settled yet and may change in a future release.

### Paths and patterns

Paths are sent as given unless they contain a pattern character (`* ? + [ ] ( ) { } | ^ $ \`), in which case they’re matched against the paths the server has data for. Globs (`navigation.*`) and Python regular expressions (`speed(OverGround|ThroughWater)`) both work.

### Time ranges

TimeRange takes any of `start`, `end` and `duration`, as ISO 8601 strings, datetimes, integer seconds or timedeltas. Date durations such as `P1D` are converted to explicit start and end times, since the server only accepts time-only durations. With no range, the last hour is used.

### Statistics

```python
stats = client.cardinality(["navigation.*"], TimeRange(duration="PT6H"))
```

gives one row per path with distinct values, nulls, zeroes, and min/max/average.

## Streaming (beta)

```python
from signalk_cli import StreamClient

client = StreamClient("http://boat.local:3000")

# The next 100 delta messages as a table
table = client.collect(["navigation.*"], count=100, policy="instant")

# Or live, row by row
with client.open(["navigation.speedOverGround"], timeout=None) as stream:
    for row in stream.rows():
        print(row.timestamp, row.source, row.value)
```

Row values keep their JSON types. Filter by source with `sources=("Teltonika",)`, and include metadata entries (units, zones, …) with `include_meta=True`.

## Errors and logging

Failed requests raise SignalKError, carrying the server’s error message and HTTP `status_code`.

Progress messages and warnings (such as a pattern matching no paths) go to the `signalk_cli` logger, which is silent unless your application configures logging:

```python
import logging

logging.basicConfig(level=logging.INFO)
```

## Pyodide / WebAssembly

`micropip.install("signalk-cli")` installs everything needed; `zeroconf` is skipped there automatically. mDNS discovery isn’t available in the browser, so pass the server’s URL to the client.
