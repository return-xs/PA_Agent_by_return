"""Tests for forming-bar close detection."""
from __future__ import annotations

import time

from pa_agent.data.bar_close_wait import (
    current_forming_ts,
    forming_bar_has_closed,
    has_forming_bar_at_head,
    is_bar_still_forming,
    seconds_until_bar_closes,
    timeframe_to_seconds,
)
from pa_agent.data.base import KlineBar


def _bar(ts: int) -> KlineBar:
    return KlineBar(
        seq=1,
        ts_open=float(ts),
        open=1.0,
        high=2.0,
        low=0.5,
        close=1.5,
        volume=10.0,
        closed=False,
    )


def test_timeframe_to_seconds() -> None:
    assert timeframe_to_seconds("5m") == 300
    assert timeframe_to_seconds("1h") == 3600
    assert timeframe_to_seconds("2h") == 7200


def test_seconds_until_bar_closes() -> None:
    ts_open = 1_000_000
    now = ts_open + 240_000  # 4 min into 5m bar
    assert seconds_until_bar_closes(ts_open, "5m", now_ms=now) == 60
    assert seconds_until_bar_closes(ts_open, "5m", now_ms=ts_open + 300_000) == 0


def test_forming_bar_has_closed_when_ts_changes() -> None:
    now_ms = int(time.time() * 1000)
    waited = now_ms - 120_000
    before = [_bar(waited), _bar(waited - 300_000)]
    after = [_bar(now_ms), _bar(waited)]
    assert current_forming_ts(before, "5m", now_ms=now_ms - 60_000) == waited
    assert not forming_bar_has_closed(waited, before, "5m", now_ms=now_ms - 60_000)
    assert forming_bar_has_closed(waited, after, "5m", now_ms=now_ms)


def test_stale_unclosed_flag_after_bar_period_not_forming() -> None:
    """TradingView-style closed=False but bar period ended → treat as closed."""
    ts_open = 1_700_000_000_000
    now_ms = ts_open + 20 * 60 * 1000  # 20m after open on 15m bar
    head = _bar(ts_open)
    assert not is_bar_still_forming(head, "15m", now_ms=now_ms)
    assert not has_forming_bar_at_head([head], "15m", now_ms=now_ms)
    assert current_forming_ts([head], "15m", now_ms=now_ms) is None
    assert forming_bar_has_closed(ts_open, [head], "15m", now_ms=now_ms)


def test_active_intraday_bar_still_forming() -> None:
    ts_open = 1_700_000_000_000
    now_ms = ts_open + 5 * 60 * 1000
    head = _bar(ts_open)
    assert is_bar_still_forming(head, "15m", now_ms=now_ms)
    assert has_forming_bar_at_head([head], "15m", now_ms=now_ms)
