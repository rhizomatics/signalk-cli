"""A small Arrow table built with nanoarrow, handed to dataframe libraries via the PyCapsule interface."""

import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

import nanoarrow as na

_TIMESTAMP = na.timestamp("us", timezone="UTC")

FEATHER_EXTENSIONS = {".feather", ".arrow", ".fea"}


def _is_number(v: object) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def as_text(v: object) -> str | None:
    if v is None or isinstance(v, str):
        return v
    if isinstance(v, (dict, list)):
        return json.dumps(v)
    return str(v)


def _epoch_us(ts: str | datetime | None) -> int | None:
    if ts is None:
        return None
    dt = datetime.fromisoformat(ts) if isinstance(ts, str) else ts
    return round(dt.timestamp() * 1_000_000)


def infer_column(values: Sequence[Any]) -> tuple[list[str | float | bool | None], Any]:
    """Pick one Arrow type for a column of JSON values: float64, bool, or string.

    Numbers (and nulls) become float64, booleans stay bool, and anything else
    — strings, objects, arrays, or a mix — becomes a string column, with
    objects and arrays JSON-encoded.
    """
    present = [v for v in values if v is not None]
    if all(_is_number(v) for v in present):
        return [None if v is None else float(v) for v in values], na.float64()
    if all(isinstance(v, bool) for v in present):
        return list(values), na.bool_()
    return [as_text(v) for v in values], na.string()


class ArrowTable:
    """A table of query results, ready to load into any Arrow-aware dataframe library.

    It implements the [Arrow PyCapsule interface](https://arrow.apache.org/docs/format/CDataInterface/PyCapsuleInterface.html),
    so it can be passed straight to polars, pandas, pyarrow, DuckDB and others
    without signalk-cli depending on any of them:

    Examples:
        ```python
        import polars as pl
        df = pl.DataFrame(table)
        import pandas as pd
        df = pd.DataFrame.from_arrow(table)  # pandas >= 3.0
        import pyarrow as pa
        t = pa.table(table)
        ```
    """

    def __init__(self, columns: dict[str, tuple[list, Any]]) -> None:
        self._columns = {name: values for name, (values, _) in columns.items()}
        self._types = {name: t for name, (_, t) in columns.items()}
        lengths = {len(v) for v in self._columns.values()}
        if len(lengths) > 1:
            raise ValueError(f"Columns have different lengths: {sorted(lengths)}")
        self._num_rows = lengths.pop() if lengths else 0

    @classmethod
    def from_rows(
        cls,
        timestamps: Sequence[str | datetime | None],
        columns: Mapping[str, Sequence[Any]],
        *,
        text_columns: Sequence[str] = (),
        timestamp_name: str = "timestamp",
    ) -> "ArrowTable":
        """Build a table with a UTC timestamp column followed by the given columns.

        Column types are inferred from the values (see `infer_column`),
        except `text_columns`, which are always strings so an empty result
        keeps the same schema.
        """
        built: dict[str, tuple[list, Any]] = {
            timestamp_name: ([_epoch_us(t) for t in timestamps], _TIMESTAMP)
        }
        for name, values in columns.items():
            if name in text_columns:
                built[name] = ([as_text(v) for v in values], na.string())
            else:
                built[name] = infer_column(values)
        return cls(built)

    @property
    def num_rows(self) -> int:
        return self._num_rows

    @property
    def column_names(self) -> list[str]:
        return list(self._columns)

    def __len__(self) -> int:
        return self._num_rows

    def __repr__(self) -> str:
        cols = ", ".join(f"{n}: {self._types[n].type.name}" for n in self._columns)
        return f"ArrowTable({self._num_rows} rows; {cols})"

    def to_pydict(self) -> dict[str, list]:
        """Return the columns as plain Python lists (timestamps as epoch microseconds)."""
        return {name: list(values) for name, values in self._columns.items()}

    def _batch(self):
        children = [
            na.c_array(values, self._types[name])
            for name, values in self._columns.items()
        ]
        schema = na.struct({name: self._types[name] for name in self._columns})
        return na.c_array_from_buffers(
            schema, self._num_rows, [None], children=children
        )

    def __arrow_c_schema__(self):
        return na.c_schema(
            na.struct({name: self._types[name] for name in self._columns})
        ).__arrow_c_schema__()

    def __arrow_c_stream__(self, requested_schema=None):
        return na.ArrayStream(self._batch()).__arrow_c_stream__(requested_schema)


def write_feather(table: ArrowTable, output: str) -> None:
    """Write a table to a Feather (Arrow IPC file) — needs pyarrow."""
    try:
        import pyarrow as pa
        from pyarrow import feather
    except ImportError:
        raise ImportError(
            "pyarrow is required for Feather output: pip install 'signalk-cli[feather]'"
        ) from None
    feather.write_feather(pa.table(table), output)
