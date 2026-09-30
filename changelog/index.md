# v3.0.0 (unreleased)

## ✨ Enhancements

- New Python API
- All the functionality of the CLI now available as a Python API to use in your own scripts, apps or notebooks
- History API: `signalk_cli.history.HistoryClient`
  - Returns tables that load straight into polars, pandas, pyarrow or DuckDB (via the small `nanoarrow` dependency; using Arrow PyCapsule interface so `pyarrow` not needed)
- Wide table column names may change in future releases
- Streaming API (beta): `signalk_cli.stream.StreamClient`
  - `open()` for a live `DeltaStream` of messages or rows, `collect()` for a table of the next N messages
- Feather files from `query` now have typed columns (UTC timestamps, floats) instead of all text
- Streaming Feather files now have typed columns (UTC timestamps, and float values where every value is a number)
- `list-paths` and `list-contexts` now accept date durations such as `--duration P1D`, like `query`

## 🚨 Breaking changes

- Plain dotted paths such as `navigation.speedOverGround` are now always literal; only `* ? + [ ( { | ^ $ \` make a pattern. Previously a `.` alone made a regex, so a path was looked up via `/paths`, matched as a substring, and dropped if the server had no data for it
- The undocumented `signalk_cli.history.history_api` and `signalk_cli.stream.stream_api` modules are gone; use `signalk_cli.history` and `signalk_cli.stream` instead

## 📚 Documentation

- Docs overhauled and updated for new APIs

# v2.2.1

## ✨ Enhancements

- Slimmed down for in-browser Python
- `zeroconf` is now optional at runtime
- Allows pure python environments like Pyodide WASM to run, at the expense of automatic SignalK server discovery over mDNS
- Used by the [`signalk-datalab-plugin`](https://github.com/rhizomatics/signalk-datalab-plugin)
- Installs directly in Pyodide/WebAssembly with `micropip.install("signalk-cli")`: platform markers skip `zeroconf` and require `niquests>=3.21.0` there

## 📝 Other changes

- Minor dependency updates

## 📚 Documentation

- Documentation switched to `properdocs` and `materialx`

# v2.2.0

## ✨ Enhancements

- Streaming now supports `values` as an output format to only emit the delta values (only useful when emitting a single path )
- Streaming allows filtering by source, e.g. `--source 'Teltonika.*'`

# v2.1.0

## ✨ Enhancements

- Better handling of websocket timeouts when following streaming deltas where SignalK server lags
- New `--include-meta` flag to add streaming metadata

## 📚 Documentation

- Improved and clarified use of `context` and `subscribe` when streaming

# v2.0.1

## ✨ Enhancements

- New module to query SignalK data streaming, with CSV, JSON and Arrow support along with ability to follow live stream

# v1.2.0

## ✨ Enhancements

- Improve handling of non-scalar values, such as `navigation.position`
- Add a `cardinality` report to analyze paths for number of unique values, nulls, mins, maxes etc

# v1.1.0

## ✨ Enhancements

- pyArrow is now an optional dependency
- Can now run using `uv run --with` form
- The native JSON response can be used as output with `raw` format
- The data headers and values can be used as output with `json` format
- Default to stdout for easier piping
- Work around SignalK limitations on time-only ISO8601 durations
- New `--pretty` flag for JSON output
- `--output` without a value will auto generate a suitable file name

# v1.0.0

## 🔬 Preview features

- First pypi release of working CLI, limited to History API
