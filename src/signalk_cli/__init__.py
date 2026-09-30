"""signalk_cli — Python clients and CLI for SignalK APIs.

The clients are importable from here or from their packages:

```python
from signalk_cli import HistoryClient, StreamClient, TimeRange
```
"""

import logging

from ._arrow import ArrowTable
from .errors import SignalKError
from .history import HistoryClient, HistoryResult, TimeRange
from .net import discover_host
from .stream import DeltaMessage, DeltaRow, DeltaStream, StreamClient

# Library convention: stay silent unless the application configures logging.
# The CLI attaches its own stderr handler per command.
logging.getLogger("signalk_cli").addHandler(logging.NullHandler())

__all__ = [
    "ArrowTable",
    "DeltaMessage",
    "DeltaRow",
    "DeltaStream",
    "HistoryClient",
    "HistoryResult",
    "SignalKError",
    "StreamClient",
    "TimeRange",
    "discover_host",
]
