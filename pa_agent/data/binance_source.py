"""Binance-based K-line data source for crypto spot and USDS-M futures.

Uses the public Binance REST API — no API key required for kline data.

Supports:
* **Spot** — ``https://api.binance.com/api/v3/klines``
* **USDS-M Futures** — ``https://fapi.binance.com/fapi/v1/klines``

Default market: USDS-M futures (perpetual contracts).
Default symbol: HYPEUSDT.

.. note::

    From mainland China you may need a proxy.  Set the ``HTTPS_PROXY``
    environment variable before launching PA Agent::

        set HTTPS_PROXY=http://127.0.0.1:7890
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

from pa_agent.data.base import (
    DataSource,
    DataSourceError,
    DataSourceTransientError,
    KlineBar,
    normalize_kline_bar,
)

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
# Constants
# ══════════════════════════════════════════════════════════════════════════════

# Binance REST API base URLs
_SPOT_API_BASE = "https://api.binance.com"
_FUTURES_API_BASE = "https://fapi.binance.com"

# Map our timeframe strings → Binance interval strings
_TF_MAP: dict[str, str] = {
    "1m":  "1m",
    "3m":  "3m",
    "5m":  "5m",
    "15m": "15m",
    "30m": "30m",
    "1h":  "1h",
    "2h":  "2h",
    "4h":  "4h",
    "6h":  "6h",
    "8h":  "8h",
    "12h": "12h",
    "1d":  "1d",
    "3d":  "3d",
    "1w":  "1w",
    "1M":  "1M",
}

# Default symbols shown in the symbol picker.
_PRESET_SPOT_SYMBOLS: tuple[str, ...] = (
    "BTCUSDT",
    "ETHUSDT",
    "BNBUSDT",
    "SOLUSDT",
    "XRPUSDT",
    "DOGEUSDT",
    "ADAUSDT",
    "AVAXUSDT",
    "LINKUSDT",
    "DOTUSDT",
    "HYPEUSDT",
)

_PRESET_FUTURES_SYMBOLS: tuple[str, ...] = (
    "BTCUSDT",
    "ETHUSDT",
    "HYPEUSDT",
    "SOLUSDT",
    "BNBUSDT",
    "XRPUSDT",
    "DOGEUSDT",
    "ADAUSDT",
    "AVAXUSDT",
    "LINKUSDT",
    "SUIUSDT",
)

_DEFAULT_SYMBOL = "HYPEUSDT"
_DEFAULT_MARKET: str = "futures"  # "futures" | "spot"

# Rate limiting: Binance hard limit is 1200 req/min; be conservative.
_MIN_REQUEST_INTERVAL_S = 0.1  # 100ms between requests


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _binance_interval(tf: str) -> str:
    """Map our timeframe string to Binance interval string."""
    if tf not in _TF_MAP:
        raise ValueError(
            f"Unsupported timeframe: {tf!r}. Use one of {list(_TF_MAP)}"
        )
    return _TF_MAP[tf]


def _kline_url(market: str) -> str:
    """Return the kline REST endpoint URL for *market*."""
    if market == "spot":
        return f"{_SPOT_API_BASE}/api/v3/klines"
    return f"{_FUTURES_API_BASE}/fapi/v1/klines"


def _parse_kline_row(row: list[Any], seq: int) -> KlineBar:
    """Parse a single Binance kline JSON array into a :class:`KlineBar`.

    Binance kline format::

        [
          0: open_time_ms,      1: open,      2: high,
          3: low,               4: close,     5: volume,
          6: close_time_ms,     7: quote_vol, 8: num_trades,
          9: taker_buy_base,   10: taker_buy_quote, 11: ignore
        ]
    """
    ts_open = int(row[0])
    return normalize_kline_bar(
        KlineBar(
            seq=seq,
            ts_open=float(ts_open),
            open=float(row[1]),
            high=float(row[2]),
            low=float(row[3]),
            close=float(row[4]),
            volume=float(row[5]),
            amount=float(row[7]) if len(row) > 7 else 0.0,
            closed=True,  # all bars except bars[0] are closed at API level
        )
    )


# ══════════════════════════════════════════════════════════════════════════════
# BinanceSource
# ══════════════════════════════════════════════════════════════════════════════

class BinanceSource(DataSource):
    """K-line data from Binance public REST API.

    Supports both **spot** and **USDS-M futures** markets.  No API key
    is required — kline data is public.

    Parameters
    ----------
    market:
        ``"futures"`` (default) or ``"spot"``.
    """

    def __init__(self, market: str = _DEFAULT_MARKET) -> None:
        if market not in ("futures", "spot"):
            raise ValueError(f"market must be 'futures' or 'spot', got {market!r}")
        self._market: str = market
        self._symbol: str = ""
        self._timeframe: str = ""
        self._connected: bool = False
        self._session: Any = None
        self._last_request_time: float = 0.0

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def connect(self) -> None:
        """Verify that ``requests`` / ``curl_cffi`` is available.

        Proxy is read from ``HTTPS_PROXY`` / ``HTTP_PROXY`` environment
        variables (required when accessing Binance from mainland China).
        """
        try:
            import requests  # noqa: F401
            self._session = requests.Session()
            # Apply proxy from environment variables.
            proxies = self._build_proxies()
            if proxies:
                self._session.proxies.update(proxies)
                logger.info("BinanceSource using proxy: %s", proxies)
            self._connected = True
            logger.info("BinanceSource connected (market=%s)", self._market)
        except ImportError:
            try:
                from curl_cffi import requests as curl_requests  # noqa: F401
                self._session = curl_requests.Session()
                proxies = self._build_proxies()
                if proxies:
                    self._session.proxies.update(proxies)
                    logger.info("BinanceSource using proxy: %s", proxies)
                self._connected = True
                logger.info("BinanceSource connected via curl_cffi (market=%s)", self._market)
            except ImportError as exc:
                raise DataSourceTransientError(
                    "requests or curl_cffi not installed"
                ) from exc

    def disconnect(self) -> None:
        if self._session is not None:
            try:
                self._session.close()
            except Exception:
                pass
        self._session = None
        self._connected = False
        self._symbol = ""
        self._timeframe = ""
        logger.info("BinanceSource disconnected")

    # ── Discovery ─────────────────────────────────────────────────────────────

    def list_symbols(self) -> list[str]:
        """Return preset popular symbols for the configured market."""
        if self._market == "futures":
            return list(_PRESET_FUTURES_SYMBOLS)
        return list(_PRESET_SPOT_SYMBOLS)

    def supported_timeframes(self) -> list[str]:
        return list(_TF_MAP.keys())

    # ── Market configuration ──────────────────────────────────────────────────

    def set_market(self, market: str) -> None:
        """Switch between ``"futures"`` and ``"spot"`` market."""
        if market not in ("futures", "spot"):
            raise ValueError(f"market must be 'futures' or 'spot', got {market!r}")
        self._market = market
        logger.info("BinanceSource market set to %s", market)

    @property
    def market(self) -> str:
        return self._market

    # ── Subscription ──────────────────────────────────────────────────────────

    def subscribe(self, symbol: str, timeframe: str) -> None:
        """Select *symbol* and *timeframe* for subsequent ``latest_snapshot`` calls.

        Symbol should be an uppercase pair like ``HYPEUSDT`` or ``BTCUSDT``.
        """
        if timeframe not in _TF_MAP:
            raise ValueError(
                f"Unsupported timeframe: {timeframe!r}. Use one of {list(_TF_MAP)}"
            )
        sym = (symbol or "").strip().upper()
        if not sym:
            raise ValueError("Symbol must not be empty")
        self._symbol = sym
        self._timeframe = timeframe
        logger.info("BinanceSource subscribed: %s %s (market=%s)", sym, timeframe, self._market)

    def unsubscribe(self) -> None:
        self._symbol = ""
        self._timeframe = ""
        logger.info("BinanceSource unsubscribed")

    # ── Data fetch ────────────────────────────────────────────────────────────

    def latest_snapshot(self, n: int) -> list[KlineBar]:
        """Return *n* bars from Binance, newest-first.

        bars[0] is the forming (unclosed) bar with ``closed=False``.
        bars[1:] are closed bars.

        Raises ``DataSourceTransientError`` on network issues.
        """
        if not self._connected:
            raise DataSourceTransientError("Not connected — call connect() first")
        if not self._symbol or not self._timeframe:
            raise DataSourceTransientError("Not subscribed — call subscribe() first")

        # Fetch extra bars to account for the forming bar.
        fetch_n = n + 5
        interval = _binance_interval(self._timeframe)
        url = _kline_url(self._market)

        params: dict[str, str | int] = {
            "symbol": self._symbol,
            "interval": interval,
            "limit": min(fetch_n + 10, 1500),
        }

        self._rate_limit()
        try:
            resp = self._session.get(url, params=params, timeout=15)
        except Exception as exc:
            raise DataSourceTransientError(
                f"Binance request failed for {self._symbol}: {exc}"
            ) from exc

        if resp.status_code == 429:
            logger.warning("Binance rate limited — backing off")
            time.sleep(2.0)
            raise DataSourceTransientError("Binance rate limited — retry later")

        if resp.status_code == 400:
            try:
                body = resp.json()
                msg = body.get("msg", resp.text)
            except Exception:
                msg = resp.text
            raise DataSourceError(
                f"Binance bad request for {self._symbol}: {msg}"
            )

        if resp.status_code != 200:
            raise DataSourceTransientError(
                f"Binance HTTP {resp.status_code} for {self._symbol}"
            )

        try:
            raw = resp.json()
        except Exception as exc:
            raise DataSourceTransientError(
                f"Binance invalid JSON response: {exc}"
            ) from exc

        if not isinstance(raw, list) or not raw:
            raise DataSourceTransientError(
                f"Binance returned no kline data for {self._symbol} {interval}"
            )

        # Build bars newest-first.  The last element in the API response
        # is the most recent (forming) bar.
        raw_reversed = raw[::-1]
        bars: list[KlineBar] = []
        for i, row in enumerate(raw_reversed):
            bar = _parse_kline_row(row, seq=i + 1)
            if i == 0:
                # bars[0] is the forming (unclosed) bar
                bar = KlineBar(
                    seq=bar.seq,
                    ts_open=bar.ts_open,
                    open=bar.open,
                    high=bar.high,
                    low=bar.low,
                    close=bar.close,
                    volume=bar.volume,
                    amount=bar.amount,
                    closed=False,
                )
            bars.append(bar)
            if len(bars) >= fetch_n:
                break

        if not bars:
            raise DataSourceTransientError(
                f"Binance returned empty data for {self._symbol} {interval}"
            )

        return bars[:n]

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _build_proxies() -> dict[str, str]:
        """Build proxy dict from environment variables."""
        proxies: dict[str, str] = {}
        for var, scheme in [("HTTPS_PROXY", "https"), ("HTTP_PROXY", "http")]:
            value = os.environ.get(var, "")
            if value:
                proxies[scheme] = value
        return proxies

    def _rate_limit(self) -> None:
        """Enforce a minimum interval between requests to avoid 429s."""
        now = time.monotonic()
        elapsed = now - self._last_request_time
        if elapsed < _MIN_REQUEST_INTERVAL_S:
            time.sleep(_MIN_REQUEST_INTERVAL_S - elapsed)
        self._last_request_time = time.monotonic()
