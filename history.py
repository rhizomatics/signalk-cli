#!/usr/bin/env python3
"""Entry point shim — runs the signalk CLI for History API via `uv run history.py`."""
from signalk_cli.cli import cli

if __name__ == "__main__":
    cli()
