"""Python API for the SignalK v1 Streaming (delta) API.

Spec: https://signalk.org/specification/1.8.2/doc/streaming_api.html
Subscribe path wildcards: https://signalk.org/specification/1.8.2/doc/subscription_protocol.html

Example:
    >>> from signalk_cli.stream import StreamClient
    >>> client = StreamClient("http://boat.local:3000")
    >>> table = client.collect(["navigation.*"], count=100, policy="instant")
    >>> import polars as pl
    >>> df = pl.DataFrame(table)
"""

import fnmatch
import json
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any, Literal, NamedTuple, Self
from urllib.parse import urlparse, urlunparse

import niquests

from .._arrow import ArrowTable
from ..errors import SignalKError
from ..net import normalise_host

STREAM_PATH = "/signalk/v1/stream"

SUBSCRIBE_POLICIES = ["none", "self", "all"]
SUBSCRIPTION_POLICIES = ["instant", "ideal", "fixed"]

Subscribe = Literal["none", "self", "all"]
Policy = Literal["instant", "ideal", "fixed"]


def to_ws_url(host: str) -> str:
    """Convert an http(s) host base URL to the ws(s) streaming endpoint URL."""
    parsed = urlparse(host)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return urlunparse((scheme, parsed.netloc, STREAM_PATH, "", "", ""))


def build_subscribe_message(
    context: str,
    paths: Sequence[str],
    *,
    period_ms: int | None = None,
    policy: str | None = None,
    min_period_ms: int | None = None,
) -> dict:
    """Build a client subscribe message for the given context and paths.

    An empty path list subscribes to all paths within the context (equivalent
    to a single "*" path). Paths are passed through unchanged — wildcarding is
    handled server-side per the SignalK Subscription Protocol: "*" at the end
    of a path matches any suffix (e.g. "navigation.*"), and "*" as a middle
    segment matches any single segment there (e.g. "propulsion.*.oilTemperature").

    period_ms/policy/min_period_ms map directly to the per-path "period",
    "policy", and "minPeriod" fields of the Subscription Protocol and are
    applied identically to every path when given. `policy`
    ("instant"/"ideal"/"fixed") defaults to "ideal" server-side if omitted;
    `min_period_ms` only affects the "instant" policy. The protocol also
    defines a per-path "format" ("delta"/"full") field, but it's omitted
    here: signalk-server rejects "full" outright and always sends delta
    messages regardless, so exposing the choice would be misleading.
    """
    entry_extra: dict[str, Any] = {}
    if period_ms is not None:
        entry_extra["period"] = period_ms
    if policy is not None:
        entry_extra["policy"] = policy
    if min_period_ms is not None:
        entry_extra["minPeriod"] = min_period_ms

    path_list = list(paths) if paths else ["*"]
    return {
        "context": context,
        "subscribe": [{"path": p, **entry_extra} for p in path_list],
    }


# ---------------------------------------------------------------------------
# Messages and rows
# ---------------------------------------------------------------------------


def source_matches(source: str, patterns: Sequence[str]) -> bool:
    """Match a `$source` string against source filter patterns (OR'd).

    No patterns means no filtering (always matches). A pattern containing
    glob metacharacters (`*`/`?`/`[`) is matched as-is via `fnmatch`;
    otherwise it's treated as a substring match, e.g. "Teltonika" matches
    the source "Teltonika.GP".
    """
    if not patterns:
        return True
    return any(
        fnmatch.fnmatch(source, p if any(c in p for c in "*?[") else f"*{p}*")
        for p in patterns
    )


def _update_source(update: dict) -> str:
    return update.get("$source") or json.dumps(update.get("source", {}))


class DeltaRow(NamedTuple):
    """One value (or meta entry) from a delta message.

    ``value`` keeps its JSON type: a number, string, bool, object, array, or None.
    ``kind`` is ``"value"``, or ``"meta"`` for metadata entries (units,
    description, zones, ...).
    """

    timestamp: str
    context: str
    source: str
    path: str
    kind: str
    value: Any


@dataclass(frozen=True)
class DeltaMessage:
    """A delta message from the server.

    Attributes:
        text: The message exactly as received.
        payload: The decoded message.
    """

    text: str
    payload: dict

    def rows(
        self, *, include_meta: bool = False, sources: Sequence[str] = ()
    ) -> list[DeltaRow]:
        """Flatten into rows, one per value.

        Args:
            include_meta: Also include each update's "meta" entries, as rows
                with ``kind="meta"``.
            sources: Only include updates whose ``$source`` matches one of
                these patterns (see :func:`source_matches`).
        """
        context = self.payload.get("context", "")
        rows: list[DeltaRow] = []
        for update in self.payload.get("updates", []):
            source = _update_source(update)
            if not source_matches(source, sources):
                continue
            timestamp = update.get("timestamp", "")
            kinds = ["values", "meta"] if include_meta else ["values"]
            for key in kinds:
                for entry in update.get(key, []):
                    rows.append(
                        DeltaRow(
                            timestamp,
                            context,
                            source,
                            entry.get("path", ""),
                            "value" if key == "values" else "meta",
                            entry.get("value"),
                        )
                    )
        return rows

    def matches_sources(self, sources: Sequence[str]) -> bool:
        """True if any update in the message comes from a matching ``$source``."""
        return not sources or any(
            source_matches(_update_source(u), sources)
            for u in self.payload.get("updates", [])
        )


def rows_to_arrow(
    rows: Sequence[DeltaRow], *, include_meta: bool = False
) -> ArrowTable:
    """Convert delta rows to a table: UTC ``timestamp``, ``context``, ``source``,
    ``path``, ``kind`` (only with ``include_meta``) and ``value``.

    ``value`` is float64 if every value is a number, otherwise text, with
    objects and arrays as JSON.
    """
    text = ["context", "source", "path", "kind"]
    columns: dict[str, list] = {
        "context": [r.context for r in rows],
        "source": [r.source for r in rows],
        "path": [r.path for r in rows],
    }
    if include_meta:
        columns["kind"] = [r.kind for r in rows]
    columns["value"] = [r.value for r in rows]
    return ArrowTable.from_rows(
        [r.timestamp or None for r in rows], columns, text_columns=text
    )


# ---------------------------------------------------------------------------
# Stream and client
# ---------------------------------------------------------------------------


class DeltaStream:
    """An open subscription. Iterate it for :class:`DeltaMessage` objects.

    Use as a context manager, or call :meth:`close`, to close the connection.

    Raises:
        SignalKError: While iterating, if the connection is lost.
    """

    def __init__(self, ws: Any) -> None:
        self._ws = ws

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._ws.close()

    def __iter__(self) -> Iterator[DeltaMessage]:
        return self.messages()

    def messages(self, count: int | None = None) -> Iterator[DeltaMessage]:
        """Yield delta messages, skipping control messages such as the server's hello.

        Stops after ``count`` messages if given, or when the server closes
        the connection.
        """
        yielded = 0
        while count is None or yielded < count:
            try:
                payload = self._ws.next_payload()
            except niquests.RequestException as e:
                raise SignalKError.from_request(e) from e
            if payload is None:
                return
            if isinstance(payload, bytes):
                payload = payload.decode("utf-8", errors="replace")
            try:
                message = json.loads(payload)
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(message, dict) or "updates" not in message:
                continue
            yield DeltaMessage(payload, message)
            yielded += 1

    def rows(
        self,
        count: int | None = None,
        *,
        include_meta: bool = False,
        sources: Sequence[str] = (),
    ) -> Iterator[DeltaRow]:
        """Yield rows from the next ``count`` messages (see :meth:`DeltaMessage.rows`)."""
        for message in self.messages(count):
            yield from message.rows(include_meta=include_meta, sources=sources)

    def collect(
        self,
        count: int | None = None,
        *,
        include_meta: bool = False,
        sources: Sequence[str] = (),
    ) -> ArrowTable:
        """Read ``count`` messages (or until the server closes) into a table.

        See :func:`rows_to_arrow` for the columns.
        """
        rows = list(self.rows(count, include_meta=include_meta, sources=sources))
        return rows_to_arrow(rows, include_meta=include_meta)


class StreamClient:
    """Client for a SignalK server's v1 Streaming (delta) API.

    Args:
        host: Server URL, e.g. ``http://boat.local:3000`` (``http://`` is
            added if there's no scheme).
        context: SignalK context to subscribe to. Accepts the wildcard
            ``*`` (or ``vessels.*``) for every vessel.
        subscribe: The connection-level auto-subscription the server adds at
            its own default rate: ``"none"`` (default), ``"self"`` or
            ``"all"``. It's in addition to the explicit subscription for
            ``context``; ``"none"`` avoids receiving your own vessel twice.
        session: A niquests session to connect with. One is created (and
            closed with the client) if not given.
    """

    def __init__(
        self,
        host: str,
        *,
        context: str = "vessels.self",
        subscribe: Subscribe = "none",
        session: niquests.Session | None = None,
    ) -> None:
        self.host = normalise_host(host).rstrip("/")
        self.context = context
        self.subscribe = subscribe
        self._owns_session = session is None
        self._session = session if session is not None else niquests.Session()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        """Close the session, if the client created it."""
        if self._owns_session:
            self._session.close()

    def open(
        self,
        paths: Sequence[str] = (),
        *,
        policy: Policy | None = "ideal",
        period: float | None = 60.0,
        min_period: float | None = None,
        timeout: float | None = 30,
    ) -> DeltaStream:
        """Connect and subscribe, returning the open :class:`DeltaStream`.

        Args:
            paths: Paths to subscribe to; all paths if empty. ``*`` wildcards
                are matched by the server, at the end of a path
                (``navigation.*``) or as a whole segment
                (``propulsion.*.oilTemperature``).
            policy: ``"instant"`` sends every change (limited by
                ``min_period``); ``"ideal"`` also resends the last value if
                nothing changes within ``period``; ``"fixed"`` sends the last
                value every ``period``.
            period: Resend interval in seconds for ``ideal``/``fixed``.
            min_period: Fastest send rate in seconds, for ``instant``.
            timeout: Seconds to wait for each message, or None to wait
                indefinitely (a quiet subscription may send nothing for a
                long time).

        Raises:
            SignalKError: If the connection fails.
        """
        try:
            resp = self._session.get(
                to_ws_url(self.host),
                params={"subscribe": self.subscribe},
                timeout=timeout,
            )
            resp.raise_for_status()
        except niquests.RequestException as e:
            raise SignalKError.from_request(e) from e
        ws = resp.extension
        if ws is None:
            raise SignalKError(
                f"{self.host} did not accept a WebSocket connection "
                "(is niquests installed with the 'ws' extra?)"
            )
        message = build_subscribe_message(
            self.context,
            paths,
            period_ms=None if period is None else int(period * 1000),
            policy=policy,
            min_period_ms=None if min_period is None else int(min_period * 1000),
        )
        ws.send_payload(json.dumps(message))
        return DeltaStream(ws)

    def collect(
        self,
        paths: Sequence[str] = (),
        *,
        count: int,
        include_meta: bool = False,
        sources: Sequence[str] = (),
        policy: Policy | None = "ideal",
        period: float | None = 60.0,
        min_period: float | None = None,
        timeout: float | None = 30,
    ) -> ArrowTable:
        """Subscribe, read ``count`` delta messages into a table, and disconnect.

        Arguments are as for :meth:`open` and :meth:`DeltaStream.collect`.
        """
        with self.open(
            paths,
            policy=policy,
            period=period,
            min_period=min_period,
            timeout=timeout,
        ) as stream:
            return stream.collect(count, include_meta=include_meta, sources=sources)
