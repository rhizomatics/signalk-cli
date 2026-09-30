# Streaming API reference

Import from `signalk_cli.stream` (or `signalk_cli` for the main classes).

Python API for the SignalK v1 Streaming (delta) API.

Spec: https://signalk.org/specification/1.8.2/doc/streaming_api.html Subscribe path wildcards: https://signalk.org/specification/1.8.2/doc/subscription_protocol.html

Examples:

```python
from signalk_cli.stream import StreamClient
client = StreamClient("http://boat.local:3000")
table = client.collect(["navigation.*"], count=100, policy="instant")
import polars as pl
df = pl.DataFrame(table)
```

## StreamClient

```python
StreamClient(
    host: str,
    *,
    context: str = "vessels.self",
    subscribe: Subscribe = "none",
    session: Session | None = None,
)
```

Client for a SignalK server’s v1 Streaming (delta) API.

Parameters:

- **`host`** (`str`) – Server URL, e.g. http://boat.local:3000 (http:// is added if there’s no scheme).
- **`context`** (`str`, default: `'vessels.self'` ) – SignalK context to subscribe to. Accepts the wildcard * (or vessels.\*) for every vessel.
- **`subscribe`** (`Subscribe`, default: `'none'` ) – The connection-level auto-subscription the server adds at its own default rate: "none" (default), "self" or "all". It’s in addition to the explicit subscription for context; "none" avoids receiving your own vessel twice.
- **`session`** (`Session | None`, default: `None` ) – A niquests session to connect with. One is created (and closed with the client) if not given.

### close

```python
close() -> None
```

Close the session, if the client created it.

### open

```python
open(
    paths: Sequence[str] = (),
    *,
    policy: Policy | None = "ideal",
    period: float | None = 60.0,
    min_period: float | None = None,
    timeout: float | None = 30,
) -> DeltaStream
```

Connect and subscribe, returning the open DeltaStream.

Parameters:

- **`paths`** (`Sequence[str]`, default: `()` ) – Paths to subscribe to; all paths if empty. * wildcards are matched by the server, at the end of a path (navigation.\*) or as a whole segment (propulsion.\*.oilTemperature).
- **`policy`** (`Policy | None`, default: `'ideal'` ) – "instant" sends every change (limited by min_period); "ideal" also resends the last value if nothing changes within period; "fixed" sends the last value every period.
- **`period`** (`float | None`, default: `60.0` ) – Resend interval in seconds for ideal/fixed.
- **`min_period`** (`float | None`, default: `None` ) – Fastest send rate in seconds, for instant.
- **`timeout`** (`float | None`, default: `30` ) – Seconds to wait for each message, or None to wait indefinitely (a quiet subscription may send nothing for a long time).

Raises:

- `SignalKError` – If the connection fails.

### collect

```python
collect(
    paths: Sequence[str] = (),
    *,
    count: int,
    include_meta: bool = False,
    sources: Sequence[str] = (),
    policy: Policy | None = "ideal",
    period: float | None = 60.0,
    min_period: float | None = None,
    timeout: float | None = 30,
) -> ArrowTable
```

Subscribe, read `count` delta messages into a table, and disconnect.

Arguments are as for open() and collect().

## DeltaStream

```python
DeltaStream(ws: Any)
```

An open subscription. Iterate it for DeltaMessage objects.

Use as a context manager, or call close(), to close the connection.

Raises:

- `SignalKError` – While iterating, if the connection is lost.

### close

```python
close() -> None
```

Close the WebSocket connection.

### messages

```python
messages(
    count: int | None = None,
) -> Iterator[DeltaMessage]
```

Yield delta messages, skipping control messages such as the server’s hello.

Stops after `count` messages if given, or when the server closes the connection.

### rows

```python
rows(
    count: int | None = None,
    *,
    include_meta: bool = False,
    sources: Sequence[str] = (),
) -> Iterator[DeltaRow]
```

Yield rows from the next `count` messages (see rows()).

### collect

```python
collect(
    count: int | None = None,
    *,
    include_meta: bool = False,
    sources: Sequence[str] = (),
) -> ArrowTable
```

Read `count` messages (or until the server closes) into a table.

See rows_to_arrow() for the columns.

## DeltaMessage

```python
DeltaMessage(text: str, payload: dict)
```

A delta message from the server.

Attributes:

- **`text`** (`str`) – The message exactly as received.
- **`payload`** (`dict`) – The decoded message.

### rows

```python
rows(
    *,
    include_meta: bool = False,
    sources: Sequence[str] = (),
) -> list[DeltaRow]
```

Flatten into rows, one per value.

Parameters:

- **`include_meta`** (`bool`, default: `False` ) – Also include each update’s “meta” entries, as rows with kind="meta".
- **`sources`** (`Sequence[str]`, default: `()` ) – Only include updates whose $source matches one of these patterns (see source_matches()).

### matches_sources

```python
matches_sources(sources: Sequence[str]) -> bool
```

True if any update in the message comes from a matching `$source`.

## DeltaRow

Bases: `NamedTuple`

One value (or meta entry) from a delta message.

`value` keeps its JSON type: a number, string, bool, object, array, or None. `kind` is `"value"`, or `"meta"` for metadata entries (units, description, zones, …).

## rows_to_arrow

```python
rows_to_arrow(
    rows: Sequence[DeltaRow], *, include_meta: bool = False
) -> ArrowTable
```

Convert delta rows to a table: UTC `timestamp`, `context`, `source`, `path`, `kind` (only with `include_meta`) and `value`.

`value` is float64 if every value is a number, otherwise text, with objects and arrays as JSON.

## source_matches

```python
source_matches(
    source: str, patterns: Sequence[str]
) -> bool
```

Match a `$source` string against source filter patterns (OR’d).

No patterns means no filtering (always matches). A pattern containing glob metacharacters (`*`/`?`/`[`) is matched as-is via `fnmatch`; otherwise it’s treated as a substring match, e.g. “Teltonika” matches the source “Teltonika.GP”.

## build_subscribe_message

```python
build_subscribe_message(
    context: str,
    paths: Sequence[str],
    *,
    period_ms: int | None = None,
    policy: str | None = None,
    min_period_ms: int | None = None,
) -> dict
```

Build a client subscribe message for the given context and paths.

An empty path list subscribes to all paths within the context (equivalent to a single “*” path). Paths are passed through unchanged — wildcarding is handled server-side per the SignalK Subscription Protocol: “*” at the end of a path matches any suffix (e.g. “navigation.*”), and “*” as a middle segment matches any single segment there (e.g. “propulsion.\*.oilTemperature”).

period_ms/policy/min_period_ms map directly to the per-path “period”, “policy”, and “minPeriod” fields of the Subscription Protocol and are applied identically to every path when given. `policy` (“instant”/”ideal”/”fixed”) defaults to “ideal” server-side if omitted; `min_period_ms` only affects the “instant” policy. The protocol also defines a per-path “format” (“delta”/”full”) field, but it’s omitted here: signalk-server rejects “full” outright and always sends delta messages regardless, so exposing the choice would be misleading.

## to_ws_url

```python
to_ws_url(host: str) -> str
```

Convert an http(s) host base URL to the ws(s) streaming endpoint URL.
