#!/usr/bin/env python3
"""Entry point shim — runs the signalk history CLI via `uv run history.py`."""
from signalk.history.cli import cli

if __name__ == "__main__":
    cli()
