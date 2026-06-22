"""CSV-file based K-line data source for offline / backtest analysis.

Supports two modes:

* **Single-file mode** — one CSV file is treated as one symbol.
* **Directory mode**   — a folder of ``*.csv`` files; each file becomes a symbol.

Expects CSV files with OHLCV columns.  Column names are auto-detected
(English and Chinese variants are recognised).  The timeframe is inferred
from the median interval between consecutive bars, or can be set by the
user in settings (``csv_timeframe``).

All bars are marked ``closed=True`` — there is no live forming bar.
"""
from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Any

from pa_agent.data.base import (
    DataSource,
    DataSourceError,
    DataSourceTransientError,
    KlineBar,
    normalize_kline_bar,
)
from pa_agent.data.datetime_ts import datetime_to_ts_ms

logger = logging.getLogger(__name__)

# ── Column name auto-detection ──────────────────────────────────────────────
# Keys are the canonical field names; values are lists of recognised aliases.
# Matching is case-insensitive and trims leading/trailing whitespace.
_COLUMN_CANDIDATES: dict[str, list[str]] = {
    "datetime": ["datetime", "date", "time", "timestamp", "日期", "时间", "datetime_utc", "ts"],
    "open":     ["open", "开盘", "开盘价", "open_price"],
    "high":     ["high", "最高", "最高价", "high_price"],
    "low":      ["low", "最低", "最低价", "low_price"],
    "close":    ["close", "收盘", "收盘价", "close_price", "price"],
    "volume":   ["volume", "vol", "成交量", "量", "volume_contracts", "tick_volume"],
}

# ── Timeframe inference ─────────────────────────────────────────────────────
# (median interval in minutes) → standard timeframe string
_INTERVAL_TO_TF: list[tuple[float, str]] = [
    (1.0, "1m"),
    (2.0, "2m"),
    (3.0, "3m"),
    (5.0, "5m"),
    (10.0, "10m"),
    (15.0, "15m"),
    (30.0, "30m"),
    (45.0, "45m"),
    (60.0, "1h"),
    (120.0, "2h"),
    (180.0, "3h"),
    (240.0, "4h"),
    (1440.0, "1d"),
    (10080.0, "1w"),
    (43200.0, "1M"),
]

# Tolerance ratio for matching a median interval to a standard timeframe.
_TF_TOLERANCE = 0.05


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _detect_columns(df_columns: list[str]) -> dict[str, str]:
    """Map canonical field names → actual column names in *df_columns*.

    Raises ``DataSourceError`` when a required column (datetime, open, high,
    low, close) cannot be resolved.  *volume* is optional.
    """
    mapping: dict[str, str] = {}
    available = {str(c).strip() for c in df_columns}

    for canonical, candidates in _COLUMN_CANDIDATES.items():
        for cand in candidates:
            # case-insensitive exact match (after stripping whitespace)
            for col in available:
                if col.lower() == cand.lower():
                    mapping[canonical] = col
                    break
            if canonical in mapping:
                break

    missing = [
        c for c in ("datetime", "open", "high", "low", "close") if c not in mapping
    ]
    if missing:
        raise DataSourceError(
            f"CSV missing required columns: {', '.join(missing)}. "
            f"Available: {sorted(available)}"
        )
    return mapping


def _infer_timeframe(timestamps_ms: list[int]) -> str:
    """Return a standard timeframe string from the median interval in *timestamps_ms*.

    *timestamps_ms* must be sorted oldest-first.
    """
    if len(timestamps_ms) < 2:
        return "1d"

    intervals_min: list[float] = []
    for i in range(1, len(timestamps_ms)):
        delta_ms = timestamps_ms[i] - timestamps_ms[i - 1]
        if delta_ms <= 0:
            continue
        intervals_min.append(delta_ms / 60_000.0)

    if not intervals_min:
        return "1d"

    # Use median to reject outliers (e.g. overnight gaps in 1h data).
    intervals_min.sort()
    n = len(intervals_min)
    if n % 2 == 1:
        median = intervals_min[n // 2]
    else:
        median = (intervals_min[n // 2 - 1] + intervals_min[n // 2]) / 2.0

    best_tf = "1d"
    best_diff = float("inf")
    for minutes, tf in _INTERVAL_TO_TF:
        if minutes == 0:
            continue
        diff = abs(median - minutes) / minutes
        if diff < best_diff and diff <= _TF_TOLERANCE:
            best_diff = diff
            best_tf = tf

    # Fallback for large intervals that didn't match any standard TF.
    if best_diff == float("inf"):
        if median >= 1440 * 7:
            best_tf = "1w"
        elif median >= 1440:
            best_tf = "1d"
        elif median >= 240:
            best_tf = "4h"
        elif median >= 60:
            best_tf = "1h"
        elif median >= 30:
            best_tf = "30m"
        elif median >= 15:
            best_tf = "15m"
        elif median >= 5:
            best_tf = "5m"
        else:
            best_tf = "1m"

    logger.debug("Inferred timeframe %s (median interval %.1f min)", best_tf, median)
    return best_tf


def _load_csv(path: Path | str) -> tuple[list[KlineBar], str]:
    """Parse one CSV file and return ``(bars_newest_first, inferred_timeframe)``.

    Raises ``DataSourceError`` on parse / column / timestamp failures.
    """
    import pandas as pd

    path = Path(path)
    if not path.exists():
        raise DataSourceError(f"CSV file not found: {path}")

    try:
        df = pd.read_csv(path)
    except Exception as exc:
        raise DataSourceError(f"Failed to read CSV {path}: {exc}") from exc

    if df.empty:
        raise DataSourceError(f"CSV file is empty: {path}")

    # ── Detect columns ────────────────────────────────────────────────────
    col_map = _detect_columns(list(df.columns))

    # Rename columns to canonical names for uniform access.
    rename = {v: k for k, v in col_map.items()}
    df = df.rename(columns=rename)

    # ── Parse timestamps ──────────────────────────────────────────────────
    try:
        ts_series = pd.to_datetime(df["datetime"])
    except Exception as exc:
        raise DataSourceError(
            f"Cannot parse datetime column in {path}. "
            f"Expected a date/time string (e.g. 2024-01-01 09:30:00). "
            f"Error: {exc}"
        ) from exc

    df["_ts_ms"] = ts_series.apply(lambda dt: datetime_to_ts_ms(dt))
    df = df.dropna(subset=["_ts_ms"])

    if df.empty:
        raise DataSourceError(f"No valid timestamps in {path}")

    # ── Coerce OHLCV to float ────────────────────────────────────────────
    for col in ("open", "high", "low", "close"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    if "volume" not in df.columns:
        df["volume"] = 0.0
    else:
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0.0)

    df = df.dropna(subset=["open", "high", "low", "close"])
    if df.empty:
        raise DataSourceError(f"No valid OHLC rows in {path}")

    # ── Sort oldest → newest, then reverse for newest-first ───────────────
    df = df.sort_values("_ts_ms", ascending=True).reset_index(drop=True)

    # Infer timeframe from sorted timestamps (oldest-first).
    ts_list = df["_ts_ms"].tolist()
    inferred_tf = _infer_timeframe(ts_list)

    # Reverse to newest-first.
    df = df.iloc[::-1].reset_index(drop=True)

    # ── Build KlineBar list ───────────────────────────────────────────────
    bars: list[KlineBar] = []
    for i, row in df.iterrows():
        ts_ms = int(row["_ts_ms"])
        bars.append(
            normalize_kline_bar(
                KlineBar(
                    seq=i + 1,
                    ts_open=ts_ms,
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row.get("volume", 0.0) or 0.0),
                    amount=float(row.get("amount", 0.0) or 0.0),
                    pct_chg=row.get("pct_chg") if "pct_chg" in row else None,
                    closed=True,  # static data — no forming bar
                )
            )
        )

    logger.info("Loaded %d bars from %s (timeframe=%s)", len(bars), path, inferred_tf)
    return bars, inferred_tf


# ══════════════════════════════════════════════════════════════════════════════
# CsvSource
# ══════════════════════════════════════════════════════════════════════════════

class CsvSource(DataSource):
    """K-line data from local CSV files.

    Suitable for offline analysis and backtesting.  No live data;
    ``latest_snapshot()`` returns cached data sliced to the requested size.

    Parameters
    ----------
    directory:
        Path to a folder of ``*.csv`` files (directory mode).  Each file
        becomes a selectable symbol.
    file_path:
        Path to a single CSV file (single-file mode).  The file stem is
        the symbol name.
    tf_override:
        When non-empty, use this timeframe string instead of auto-inferring
        from bar intervals.
    """

    def __init__(
        self,
        directory: str = "",
        file_path: str = "",
        tf_override: str = "",
    ) -> None:
        self._directory: str = directory
        self._file_path: str = file_path
        self._tf_override: str = tf_override
        self._symbol: str = ""
        self._timeframe: str = ""
        self._connected: bool = False
        # In-memory cache: symbol → (bars_newest_first, timeframe)
        self._cache: dict[str, tuple[list[KlineBar], str]] = {}

    # ── Configuration ─────────────────────────────────────────────────────────

    def set_path(self, *, directory: str = "", file_path: str = "") -> None:
        """Update the CSV path(s) and clear the in-memory cache."""
        self._directory = directory
        self._file_path = file_path
        self._cache.clear()
        logger.info("CsvSource path updated: dir=%r file=%r", directory, file_path)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def connect(self) -> None:
        """Verify that pandas is available.  No data is loaded yet."""
        try:
            import pandas  # noqa: F401
            self._connected = True
            logger.info("CsvSource connected (pandas available)")
        except ImportError as exc:
            raise DataSourceTransientError(
                "pandas not installed — run: pip install pandas"
            ) from exc

    def disconnect(self) -> None:
        self._connected = False
        self._cache.clear()
        self._symbol = ""
        self._timeframe = ""
        logger.info("CsvSource disconnected")

    # ── Discovery ─────────────────────────────────────────────────────────────

    def list_symbols(self) -> list[str]:
        """Return available symbol names from the configured CSV path(s).

        - Directory mode: stems of ``*.csv`` files in the directory.
        - Single-file mode: stem of the configured file.
        """
        if self._directory:
            dir_path = Path(self._directory)
            if not dir_path.is_dir():
                logger.warning("CSV directory not found: %s", self._directory)
                return []
            symbols = sorted(
                p.stem for p in dir_path.glob("*.csv") if p.is_file()
            )
            logger.debug("CsvSource directory scan: %d symbols", len(symbols))
            return symbols

        if self._file_path:
            stem = Path(self._file_path).stem
            return [stem]

        return []

    def supported_timeframes(self) -> list[str]:
        return [
            "1m", "2m", "3m", "5m", "10m", "15m", "30m", "45m",
            "1h", "2h", "3h", "4h", "1d", "1w", "1M",
        ]

    # ── Subscription ──────────────────────────────────────────────────────────

    def subscribe(self, symbol: str, timeframe: str = "") -> None:
        """Load *symbol* from CSV and cache its bars.

        *timeframe* is optional — when empty, the timeframe is auto-inferred
        from the median interval between bars.  The ``csv_timeframe`` setting
        (passed via ``tf_override`` at construction) takes highest priority.
        """
        if not self._connected:
            raise DataSourceTransientError("Not connected — call connect() first")

        self._symbol = symbol
        self._timeframe = timeframe

        # Resolve file path for this symbol.
        file_path = self._resolve_path(symbol)
        if file_path is None:
            raise DataSourceError(
                f"CSV file not found for symbol {symbol!r}. "
                f"Directory={self._directory or '<none>'}, "
                f"File={self._file_path or '<none>'}"
            )

        # Load and cache.
        if symbol not in self._cache:
            try:
                bars, inferred_tf = _load_csv(file_path)
            except DataSourceError:
                raise
            except Exception as exc:
                raise DataSourceTransientError(
                    f"Failed to load CSV for {symbol}: {exc}"
                ) from exc
            self._cache[symbol] = (bars, inferred_tf)
        else:
            _, inferred_tf = self._cache[symbol]

        # Determine final timeframe: override > user-specified > inferred.
        if self._tf_override:
            self._timeframe = self._tf_override
        elif not self._timeframe:
            self._timeframe = inferred_tf

        logger.info(
            "CsvSource subscribed: %s %s (cache_size=%d)",
            symbol, self._timeframe, len(self._cache),
        )

    def unsubscribe(self) -> None:
        self._symbol = ""
        self._timeframe = ""
        logger.info("CsvSource unsubscribed")

    # ── Data fetch ────────────────────────────────────────────────────────────

    def latest_snapshot(self, n: int) -> list[KlineBar]:
        """Return the *n* most recent bars (newest-first, all closed).

        Raises ``DataSourceTransientError`` if not connected or subscribed.
        """
        if not self._connected:
            raise DataSourceTransientError("Not connected — call connect() first")
        if not self._symbol:
            raise DataSourceTransientError("Not subscribed — call subscribe() first")

        entry = self._cache.get(self._symbol)
        if entry is None:
            raise DataSourceTransientError(
                f"{self._symbol!r} not in cache — call subscribe() first"
            )

        bars, _ = entry
        return bars[:n]

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _resolve_path(self, symbol: str) -> str | None:
        """Return the filesystem path for *symbol*, or ``None``."""
        # Directory mode: look for <symbol>.csv in the directory.
        if self._directory:
            candidate = Path(self._directory) / f"{symbol}.csv"
            if candidate.is_file():
                return str(candidate)

        # Single-file mode: the file itself is the only symbol.
        if self._file_path:
            file_stem = Path(self._file_path).stem
            if symbol == file_stem:
                return self._file_path

        return None
