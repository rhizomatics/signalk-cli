"""SignalK v1 Streaming (delta) API client.

Spec: https://signalk.org/specification/1.8.2/doc/streaming_api.html
Subscribe path wildcards: https://signalk.org/specification/1.8.2/doc/subscription_protocol.html
"""

import json
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlparse, urlunparse

import niquests

STREAM_PATH = "/signalk/v1/stream"

SUBSCRIBE_POLICIES = ["none", "self", "all"]
SUBSCRIPTION_POLICIES = ["instant", "ideal", "fixed"]


def to_ws_url(host: str) -> str:
    """Convert an http(s) host base URL to the ws(s) streaming endpoint URL."""
    parsed = urlparse(host)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return urlunparse((scheme, parsed.netloc, STREAM_PATH, "", "", ""))


def open_stream(host: str, subscribe: str, timeout: float = 30):
    """Open a WebSocket connection to the SignalK streaming endpoint.

    Returns the underlying HTTP extension object, used to send/receive frames
    via `send_payload`/`next_payload`.
    """
    url = to_ws_url(host)
    resp = niquests.get(url, params={"subscribe": subscribe}, timeout=timeout)
    resp.raise_for_status()
    return resp.extension


def build_subscribe_message(
    context: str,
    paths: list[str],
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

    path_list = paths if paths else ["*"]
    return {
        "context": context,
        "subscribe": [{"path": p, **entry_extra} for p in path_list],
    }


def iter_deltas(ws, count: int | None = None) -> Iterator[tuple[str, dict[str, Any]]]:
    """Yield (raw_text, parsed) pairs for delta messages from an open WebSocket connection.

    Control messages without an "updates" key (e.g. the initial Hello message)
    are skipped. Stops after `count` deltas if given, or when the server
    closes the connection.
    """
    yielded = 0
    while count is None or yielded < count:
        payload = ws.next_payload()
        if payload is None:
            return
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8", errors="replace")
        try:
            message = json.loads(payload)
        except (TypeError, json.JSONDecodeError):
            continue
        if "updates" not in message:
            continue
        yield payload, message
        yielded += 1
