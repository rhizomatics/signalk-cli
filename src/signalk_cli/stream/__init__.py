"""signalk_cli.stream — Python client and CLI for the SignalK v1 Streaming (delta) API."""

from .._arrow import ArrowTable
from ..errors import SignalKError
from .api import (
    STREAM_PATH,
    DeltaMessage,
    DeltaRow,
    DeltaStream,
    StreamClient,
    build_subscribe_message,
    rows_to_arrow,
    source_matches,
    to_ws_url,
)

__all__ = [
    "STREAM_PATH",
    "ArrowTable",
    "DeltaMessage",
    "DeltaRow",
    "DeltaStream",
    "SignalKError",
    "StreamClient",
    "build_subscribe_message",
    "rows_to_arrow",
    "source_matches",
    "to_ws_url",
]
