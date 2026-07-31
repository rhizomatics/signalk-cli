"""Entry point for `python -m signalk` — lists supported API modules."""

print("Supported SignalK APIs:")
print("  signalk_cli.history  — SignalK v2 History API")
print("  signalk_cli.stream   — SignalK v1 Streaming (delta) API")
print()
print("Usage: python -m signalk_cli.<api> [COMMAND] [OPTIONS]")
print("       python -m signalk_cli.history --help")
print("       python -m signalk_cli.stream --help")
