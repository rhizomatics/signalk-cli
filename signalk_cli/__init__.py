"""signalk_cli — Python client and CLI for SignalK v2 APIs"""

from .history_api import (
    HISTORY_BASE,
    api_error,
    apply_time_default,
    expand_paths,
    fetch_default_provider,
    fetch_server_paths,
    get_cached_provider,
    normalise_host,
    resolve_provider,
    save_cached_provider,
)
from .output import extract_rows, write_csv, write_feather

__all__ = [
    "HISTORY_BASE",
    "api_error",
    "apply_time_default",
    "expand_paths",
    "extract_rows",
    "fetch_default_provider",
    "fetch_server_paths",
    "get_cached_provider",
    "normalise_host",
    "resolve_provider",
    "save_cached_provider",
    "write_csv",
    "write_feather",
]
