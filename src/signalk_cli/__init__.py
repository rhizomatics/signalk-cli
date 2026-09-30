"""signalk_cli — Python clients and CLI for SignalK APIs."""

import logging

# Library convention: stay silent unless the application configures logging.
# The CLI attaches its own stderr handler per command.
logging.getLogger("signalk_cli").addHandler(logging.NullHandler())
