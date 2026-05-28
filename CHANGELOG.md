# v1.1.0
- pyArrow is now an optional dependency
- Can now run using `uv run --with` form
- The native JSON response can be used as output with `raw` format
- The data headers and values can be used as output with `json` format
- Default to stdout for easier piping
- Work around SignalK limitations on time-only ISO8601 durations
- New `--pretty` flag for JSON output
- `--output` without a value will auto generate a suitable file name
# v1.0.0
- First pypi release of working CLI, limited to History API