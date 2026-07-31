"""signalk_cli.stream — Python client and CLI for the SignalK v1 Streaming (delta) API."""

from .output import extract_delta_rows, write_csv_delta, write_json_delta
from .stream_api import (
    STREAM_PATH,
    build_subscribe_message,
    iter_deltas,
    open_stream,
    to_ws_url,
)

__all__ = [
    "STREAM_PATH",
    "build_subscribe_message",
    "extract_delta_rows",
    "iter_deltas",
    "open_stream",
    "to_ws_url",
    "write_csv_delta",
    "write_json_delta",
]
