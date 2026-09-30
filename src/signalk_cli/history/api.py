"""Python API for the SignalK v2 History API.

Example:
    >>> from signalk_cli.history import HistoryClient, TimeRange
    >>> with HistoryClient("http://boat.local:3000") as client:
    ...     table = client.query(["navigation.speedOverGround"], TimeRange(duration="PT1H"))
    >>> import polars as pl
    >>> df = pl.DataFrame(table)
"""

import fnmatch
import logging
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal, Self

import nanoarrow as na
import niquests

from .._arrow import ArrowTable
from ..errors import SignalKError
from ..net import CACHE_DIR, normalise_host
from . import _results
from ._time import TimeRange

logger = logging.getLogger("signalk_cli")

HISTORY_BASE = "/signalk/v2/api/history"

AGGREGATION_METHODS = (
    "average",
    "min",
    "max",
    "first",
    "last",
    "mid",
    "middle_index",
    "sma",
    "ema",
)

Shape = Literal["long", "wide"]

# "." is left out: it's in every SignalK path, so a plain dotted path is a literal
_PATTERN_CHARS = set(r"*+?[](){}|^$\\")
_GLOB_ONLY_RE = re.compile(r"^[^.+(){}|^$\\]+$")


# ---------------------------------------------------------------------------
# Path specs and patterns
# ---------------------------------------------------------------------------


def build_path_specs(
    paths: Sequence[str],
    aggregation: str | None = None,
    samples: int | None = None,
    alpha: float | None = None,
) -> tuple[str, bool]:
    """Build the ``paths`` query parameter, with an aggregation method per path.

    Paths that already carry a method (``navigation.speedOverGround:sma:5``)
    pass through unchanged. With no aggregation and no inline methods, each
    path is requested as min, average and max (wide shape), except position
    paths, which don't support those and are requested with ``mid``.

    Returns:
        ``(paths_param, wide)``, where ``wide`` says the response should be
        read in the wide shape.
    """
    if aggregation:
        specs = []
        for path in paths:
            if ":" in path:
                specs.append(path)
                continue
            spec = f"{path}:{aggregation}"
            if aggregation == "sma" and samples is not None:
                spec += f":{samples}"
            elif aggregation == "ema" and alpha is not None:
                spec += f":{alpha}"
            specs.append(spec)
        return ",".join(specs), False

    if any(":" in p for p in paths):
        return ",".join(paths), False

    specs = []
    for p in paths:
        if _results.POSITION_RE.fullmatch(p):
            specs.append(f"{p}:mid")
        else:
            specs.extend(f"{p}:{m}" for m in ("min", "average", "max"))
    return ",".join(specs), True


def _is_pattern(path: str) -> bool:
    return ":" not in path and any(c in path for c in _PATTERN_CHARS)


def _compile(pattern: str) -> re.Pattern:
    if _GLOB_ONLY_RE.match(pattern):
        return re.compile(fnmatch.translate(pattern))
    try:
        return re.compile(pattern)
    except re.PatternError:
        logger.info("Note: '%s' is not valid regex, treating as glob", pattern)
        return re.compile(fnmatch.translate(pattern))


def match_paths(patterns: Sequence[str], available: Sequence[str]) -> list[str]:
    """Expand path patterns against a list of known paths.

    Literal paths and inline specs (``path:method``) pass through unchanged.
    A path is a pattern if it contains any of ``* ? + [ ] ( ) { } | ^ $ \\``
    (a ``.`` alone doesn't count, so ``navigation.speedOverGround`` is literal).
    Patterns are matched as globs (``navigation.*``) when they only use glob
    characters, otherwise as Python regular expressions (searched, not
    anchored); an invalid regex falls back to a glob.

    Returns:
        The literal paths in the order given, followed by all matched paths, sorted.
    """
    literals = [p for p in patterns if not _is_pattern(p)]
    matched: set[str] = set()
    for pattern in (p for p in patterns if _is_pattern(p)):
        rx = _compile(pattern)
        hits = {path for path in available if rx.search(path)}
        if not hits:
            logger.warning("Warning: '%s' matched no paths", pattern)
        matched |= hits
    return literals + sorted(matched)


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


class HistoryResult:
    """A /values response, with conversions to tables and statistics.

    Attributes:
        payload: The decoded JSON response, as the server sent it.
        wide: True when the request asked for min/average/max per path, so
            the result reads naturally in the wide shape.
    """

    def __init__(self, payload: dict, *, wide: bool = False) -> None:
        self.payload = payload
        self.wide = wide

    @property
    def paths(self) -> list[str]:
        """Distinct paths in the response, in the order the server listed them."""
        return list(
            dict.fromkeys(v.get("path", "") for v in self.payload.get("values", []))
        )

    def to_arrow(self, shape: Shape | None = None) -> ArrowTable:
        """Convert to a table; see :meth:`HistoryClient.query` for the two shapes.

        Args:
            shape: ``"long"`` or ``"wide"``. Defaults to wide when the request
                asked for min/average/max, otherwise long.
        """
        if (shape or ("wide" if self.wide else "long")) == "wide":
            timestamps, paths, cols = _results.wide_rows(self.payload)
            return ArrowTable.from_rows(
                timestamps, {"path": paths, **cols}, text_columns=["path"]
            )
        timestamps, paths, values = _results.long_rows(self.payload)
        return ArrowTable.from_rows(
            timestamps, {"path": paths, "value": values}, text_columns=["path"]
        )

    def cardinality(self) -> list[dict[str, Any]]:
        """Per-path statistics; see :meth:`HistoryClient.cardinality`."""
        return _results.cardinality(self.payload)


def _cardinality_table(rows: list[dict[str, Any]]) -> ArrowTable:
    columns: dict[str, tuple[list, Any]] = {
        "path": ([r["path"] for r in rows], na.string())
    }
    for col in _results.CARDINALITY_COLUMNS[1:]:
        values = [r[col] for r in rows]
        if col in ("min", "max", "average"):
            columns[col] = (
                [None if v is None else float(v) for v in values],
                na.float64(),
            )
        else:
            columns[col] = (values, na.int64())
    return ArrowTable(columns)


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class HistoryClient:
    """Client for a SignalK server's v2 History API.

    Args:
        host: Server URL, e.g. ``http://boat.local:3000`` (``http://`` is
            added if there's no scheme).
        provider: History provider plugin id. Defaults to the server's
            default provider, looked up on first use.
        context: SignalK context to query, e.g. ``vessels.self``.
        session: A niquests session to send requests with. One is created
            (and closed with the client) if not given.
        cache: Remember each server's default provider on disk, under
            ``~/.cache/signalk-cli``, to save a request next time.
        timeout: Seconds to wait for each response.

    Raises:
        SignalKError: From any method, when a request fails.
    """

    def __init__(
        self,
        host: str,
        *,
        provider: str | None = None,
        context: str = "vessels.self",
        session: niquests.Session | None = None,
        cache: bool = False,
        timeout: float = 60,
    ) -> None:
        self.host = normalise_host(host).rstrip("/")
        self.base_url = self.host + HISTORY_BASE
        self.context = context
        self.timeout = timeout
        self._provider = provider
        self._provider_resolved = provider is not None
        self._cache = cache
        self._owns_session = session is None
        self._session = session if session is not None else niquests.Session()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        """Close the session, if the client created it."""
        if self._owns_session:
            self._session.close()

    # -- low level ----------------------------------------------------------

    def fetch(
        self, endpoint: str, params: dict | None = None, *, stream: bool = False
    ) -> niquests.Response:
        """GET a History API endpoint (e.g. ``"values"``, ``"paths"``) and return the response.

        A low-level escape hatch for callers that want the raw response body;
        the other methods are usually more convenient.
        """
        try:
            resp = self._session.get(
                f"{self.base_url}/{endpoint}",
                params=params,
                timeout=self.timeout,
                stream=stream,
            )
            resp.raise_for_status()
        except niquests.RequestException as e:
            raise SignalKError.from_request(e) from e
        return resp

    def _get_json(self, endpoint: str, params: dict | None = None) -> Any:
        return self.fetch(endpoint, params).json()

    # -- providers ----------------------------------------------------------

    def providers(self) -> dict[str, dict[str, Any]]:
        """Registered history providers, as ``{id: {"isDefault": bool, ...}}``."""
        return self._get_json("_providers")

    def default_provider(self) -> str:
        """The id of the server's default history provider."""
        return self._get_json("_providers/_default")["id"]

    def _provider_cache_file(self) -> Path:
        return CACHE_DIR / f"{re.sub(r'[^\w.-]', '_', self.host)}.provider"

    @property
    def provider(self) -> str | None:
        """The provider used for requests: the one given, else the server's default.

        The default is fetched once (or read from the disk cache if enabled).
        If it can't be fetched, requests go without one and the server picks.
        """
        if self._provider_resolved:
            return self._provider
        self._provider_resolved = True
        cache_file = self._provider_cache_file()
        if self._cache:
            try:
                self._provider = cache_file.read_text().strip() or None
            except OSError:
                pass
        if not self._provider:
            try:
                self._provider = self.default_provider()
            except SignalKError as e:
                logger.warning("Warning: could not fetch default provider: %s", e)
                return None
            if self._cache:
                try:
                    CACHE_DIR.mkdir(parents=True, exist_ok=True)
                    cache_file.write_text(self._provider)
                except OSError:
                    pass
        return self._provider

    def request_params(
        self, time: TimeRange | None = None, **extra: Any
    ) -> dict[str, Any]:
        """Query parameters for a request: the time range, provider, and any extras given.

        Useful with :meth:`fetch`; ``None`` extras are left out.
        """
        params: dict[str, Any] = (time or TimeRange()).resolved().params()
        if self.provider:
            params["provider"] = self.provider
        params.update({k: v for k, v in extra.items() if v is not None})
        return params

    # -- discovery ----------------------------------------------------------

    def contexts(self, time: TimeRange | None = None) -> list[str]:
        """Contexts (vessels, aircraft, ...) with data in the time range, sorted."""
        return sorted(self._get_json("contexts", self.request_params(time)))

    def paths(self, time: TimeRange | None = None) -> list[str]:
        """Paths with data in the time range, sorted."""
        return sorted(self._get_json("paths", self.request_params(time)))

    def expand_paths(
        self, patterns: Sequence[str], time: TimeRange | None = None
    ) -> list[str]:
        """Expand glob/regex patterns to the matching paths with data in the time range.

        Only fetches the server's path list if there's a pattern to match.
        See :func:`match_paths` for the matching rules.
        """
        if not any(_is_pattern(p) for p in patterns):
            return list(patterns)
        logger.info("Resolving patterns against server paths...")
        return match_paths(patterns, self.paths(time))

    # -- data ---------------------------------------------------------------

    def value_params(
        self,
        paths: Sequence[str],
        time: TimeRange | None = None,
        *,
        aggregation: str | None = None,
        samples: int | None = None,
        alpha: float | None = None,
        resolution: str | int | None = None,
        context: str | None = None,
        expand: bool = True,
    ) -> tuple[dict[str, Any], bool]:
        """The query parameters :meth:`values` sends, and whether the result is wide.

        Useful with :meth:`fetch` to get the raw response body. Arguments are
        as for :meth:`values`.
        """
        time = (time or TimeRange()).resolved()
        resolved = self.expand_paths(paths, time) if expand else list(paths)
        if not resolved:
            raise ValueError("No paths to query")
        spec, wide = build_path_specs(resolved, aggregation, samples, alpha)
        params = self.request_params(
            time,
            paths=spec,
            context=context or self.context,
            resolution=resolution,
        )
        return params, wide

    def values(
        self,
        paths: Sequence[str],
        time: TimeRange | None = None,
        *,
        aggregation: str | None = None,
        samples: int | None = None,
        alpha: float | None = None,
        resolution: str | int | None = None,
        context: str | None = None,
        expand: bool = True,
    ) -> HistoryResult:
        """Fetch values for the given paths, as a :class:`HistoryResult`.

        Args:
            paths: Paths, glob/regex patterns, or inline specs such as
                ``navigation.speedOverGround:sma:5``.
            time: Time range; defaults to the last hour.
            aggregation: Method applied to each path without an inline spec,
                one of :data:`AGGREGATION_METHODS`. If neither this nor
                inline specs are given, min/average/max are fetched (wide).
            samples: Window size for ``sma``.
            alpha: Smoothing factor for ``ema``.
            resolution: Sample window, as seconds or an expression like ``1m``.
            context: Overrides the client's context for this request.
            expand: Expand patterns in ``paths`` first (see :meth:`expand_paths`).

        Raises:
            ValueError: If no paths are left to query after expansion.
        """
        params, wide = self.value_params(
            paths,
            time,
            aggregation=aggregation,
            samples=samples,
            alpha=alpha,
            resolution=resolution,
            context=context,
            expand=expand,
        )
        return HistoryResult(self._get_json("values", params), wide=wide)

    def query(
        self,
        paths: Sequence[str],
        time: TimeRange | None = None,
        *,
        shape: Shape | None = None,
        aggregation: str | None = None,
        samples: int | None = None,
        alpha: float | None = None,
        resolution: str | int | None = None,
        context: str | None = None,
    ) -> ArrowTable:
        """Fetch values as a table for polars, pandas, pyarrow, DuckDB, etc.

        Both shapes have one row per timestamp and path, with a UTC
        ``timestamp`` column and a ``path`` column:

        - **long**: a single ``value`` column. It's float64 if every value is
          a number, otherwise text, with objects and arrays as JSON.
        - **wide**: ``min_value``/``avg_value``/``max_value`` for number paths,
          and one column per element for array paths (``longitude``/``latitude``
          for positions, otherwise ``value_0``, ``value_1``, ...).

        !!! warning
            Wide column names may change in a future release.

        Args:
            shape: Defaults to wide if no aggregation or inline spec is
                given (min/average/max are fetched), otherwise long.
            paths, time, aggregation, samples, alpha, resolution, context:
                As for :meth:`values`.
        """
        return self.values(
            paths,
            time,
            aggregation=aggregation,
            samples=samples,
            alpha=alpha,
            resolution=resolution,
            context=context,
        ).to_arrow(shape)

    def cardinality(
        self,
        paths: Sequence[str] = ("*",),
        time: TimeRange | None = None,
        *,
        resolution: str | int | None = None,
        context: str | None = None,
    ) -> ArrowTable:
        """Per-path statistics over the time range, as a table.

        Columns: ``path``, ``distinct_values``,
        ``distinct_values_2_decimal_places``, ``nulls``, ``zeroes``, ``min``,
        ``max``, ``average``. ``min``/``max``/``average`` are null unless every
        value of the path is a number.
        """
        return _cardinality_table(
            self.cardinality_rows(paths, time, resolution=resolution, context=context)
        )

    def cardinality_rows(
        self,
        paths: Sequence[str] = ("*",),
        time: TimeRange | None = None,
        *,
        resolution: str | int | None = None,
        context: str | None = None,
    ) -> list[dict[str, Any]]:
        """Like :meth:`cardinality`, as a list of dicts."""
        time = (time or TimeRange()).resolved()
        resolved = self.expand_paths(paths, time)
        if not resolved:
            raise ValueError("No paths to query")
        params = self.request_params(
            time,
            paths=",".join(resolved),
            context=context or self.context,
            resolution=resolution,
        )
        return _results.cardinality(self._get_json("values", params))
