# Tables, errors and discovery

## ArrowTable

```python
ArrowTable(columns: dict[str, tuple[list, Any]])
```

A table of query results, ready to load into any Arrow-aware dataframe library.

It implements the [Arrow PyCapsule interface](https://arrow.apache.org/docs/format/CDataInterface/PyCapsuleInterface.html), so it can be passed straight to polars, pandas, pyarrow, DuckDB and others without signalk-cli depending on any of them:

Examples:

```python
import polars as pl
df = pl.DataFrame(table)
import pandas as pd
df = pd.DataFrame.from_arrow(table)  # pandas >= 3.0
import pyarrow as pa
t = pa.table(table)
```

### num_rows

```python
num_rows: int
```

### column_names

```python
column_names: list[str]
```

### to_pydict

```python
to_pydict() -> dict[str, list]
```

Return the columns as plain Python lists (timestamps as epoch microseconds).

## SignalKError

```python
SignalKError(
    message: str, *, status_code: int | None = None
)
```

Bases: `Exception`

A request to a SignalK server failed.

Attributes:

- **`status_code`** – HTTP status of the failed response, or None if the server couldn’t be reached.

### from_request

```python
from_request(exc: RequestException) -> SignalKError
```

Wrap a niquests exception, using the server’s error message if it sent one.

## discover_host

```python
discover_host(timeout: float = 5.0) -> str | None
```

Browse mDNS for a SignalK server and return its base URL, or None.
