"""signalk_cli.history — Python client and CLI for the SignalK v2 History API."""

from .._arrow import ArrowTable
from ..errors import SignalKError
from ._time import TimeRange
from .api import (
    AGGREGATION_METHODS,
    HISTORY_BASE,
    HistoryClient,
    HistoryResult,
    build_path_specs,
    match_paths,
)

__all__ = [
    "AGGREGATION_METHODS",
    "HISTORY_BASE",
    "ArrowTable",
    "HistoryClient",
    "HistoryResult",
    "SignalKError",
    "TimeRange",
    "build_path_specs",
    "match_paths",
]
