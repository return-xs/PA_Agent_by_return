"""ChartWidget — pyqtgraph-based K-line chart with EMA20 and overlay lines.

Tasks 14.2 + 14.5:
  - Renders N candles, EMA20 line, and sequence-number labels.
  - Draws entry/TP/SL horizontal lines when order_type != "不下单".
  - 30 Hz QTimer throttles redraws so the 1 Hz data thread never blocks the UI.
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import QTimer

from pa_agent.gui.widgets.candle_item import CandleItem
from pa_agent.gui.widgets.overlay_lines import OverlayLines
from pa_agent.gui.widgets.seq_label_item import SeqLabelItem
from pa_agent.util.trade_metrics import is_long_direction

if TYPE_CHECKING:
    from pa_agent.data.base import KlineFrame

# ── Constants ─────────────────────────────────────────────────────────────────

_TIMER_INTERVAL_MS = 33  # ~30 Hz
_EMA_COLOR = (255, 200, 0)  # amber
_NO_ORDER_TEXT = "不下单"


class ChartWidget(pg.PlotWidget):
    """Interactive K-line chart widget.

    Parameters
    ----------
    parent:
        Optional Qt parent widget.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent=parent)

        # Configure plot appearance
        self.setBackground("#0d1117")
        self.showGrid(x=False, y=True, alpha=0.3)
        self.getPlotItem().setLabel("left", "Price")

        # Internal state
        self._latest_frame: KlineFrame | None = None
        self._dirty: bool = False
        self._candle_items: list[CandleItem] = []
        self._seq_labels: list[SeqLabelItem] = []
        self._ema_line: pg.PlotDataItem | None = None
        self._overlay = OverlayLines()
        self._pending_decision: dict | None = None
        self._direction_items: list[pg.GraphicsItem] = []

        # 30 Hz redraw timer (task 14.5)
        self._timer = QTimer(self)
        self._timer.setInterval(_TIMER_INTERVAL_MS)
        self._timer.timeout.connect(self._on_timer)
        self._timer.start()

    # ── Public API ────────────────────────────────────────────────────────────

    def set_frame(self, frame: "KlineFrame") -> None:
        """Cache the latest KlineFrame; actual redraw happens on the timer."""
        self._latest_frame = frame
        self._dirty = True

    def set_decision(self, decision: dict) -> None:
        """Draw or clear entry/TP/SL lines and direction marker from the AI decision."""
        self._pending_decision = decision
        order_type = decision.get("order_type", _NO_ORDER_TEXT)
        if order_type == _NO_ORDER_TEXT:
            self._overlay.clear_lines(self)
            self._clear_direction_marker()
            self._pending_decision = None
            return

        entry = decision.get("entry_price")
        tp = decision.get("take_profit_price")
        sl = decision.get("stop_loss_price")

        if entry is not None and tp is not None and sl is not None:
            try:
                self._overlay.set_lines(self, float(entry), float(tp), float(sl))
            except (TypeError, ValueError):
                self._overlay.clear_lines(self)
        else:
            self._overlay.clear_lines(self)

        self._update_direction_marker()

    def reset(self) -> None:
        """Clear all chart items (candles, labels, EMA, overlay lines)."""
        self._overlay.clear_lines(self)
        self._clear_direction_marker()
        self._pending_decision = None
        self._clear_candles_and_labels()
        if self._ema_line is not None:
            self.removeItem(self._ema_line)
            self._ema_line = None
        self._latest_frame = None
        self._dirty = False

    # ── Timer slot ────────────────────────────────────────────────────────────

    def _on_timer(self) -> None:
        """Called every ~33 ms; redraws only when a new frame is available."""
        if not self._dirty or self._latest_frame is None:
            return
        self._dirty = False
        self._render_frame(self._latest_frame)

    # ── Internal rendering ────────────────────────────────────────────────────

    def _render_frame(self, frame: "KlineFrame") -> None:
        """Rebuild all candle items, EMA line, and sequence labels."""
        self._clear_candles_and_labels()
        if self._ema_line is not None:
            self.removeItem(self._ema_line)
            self._ema_line = None

        bars = frame.bars
        n = len(bars)
        if n == 0:
            return

        # bars[0] is newest (seq=1); we want x=0 for oldest, x=n-1 for newest
        # so x_pos for bars[i] = (n - 1 - i)
        ema_x: list[float] = []
        ema_y: list[float] = []

        for i, bar in enumerate(bars):
            x_pos = n - 1 - i  # oldest bar at x=0, newest at x=n-1

            # Candle
            candle = CandleItem(bar, x_pos)
            self.addItem(candle)
            self._candle_items.append(candle)

            # Sequence label above the high — only odd seq numbers (1, 3, 5, …)
            if bar.seq % 2 == 1:
                label_y = bar.high
                seq_label = SeqLabelItem(bar.seq, x_pos, label_y)
                self.addItem(seq_label)
                self._seq_labels.append(seq_label)

            # EMA20 point (skip NaN)
            ema_val = frame.indicators.ema20[i]
            if not math.isnan(ema_val):
                ema_x.append(float(x_pos))
                ema_y.append(ema_val)

        # EMA20 line
        if ema_x:
            self._ema_line = pg.PlotDataItem(
                x=np.array(ema_x),
                y=np.array(ema_y),
                pen=pg.mkPen(color=_EMA_COLOR, width=1),
            )
            self.addItem(self._ema_line)

        self._update_direction_marker()

    def _clear_direction_marker(self) -> None:
        for item in self._direction_items:
            self.removeItem(item)
        self._direction_items.clear()

    def _update_direction_marker(self) -> None:
        """Draw ▲/▼ at newest bar × entry price for long/short."""
        self._clear_direction_marker()
        decision = self._pending_decision
        frame = self._latest_frame
        if decision is None or frame is None:
            return
        if decision.get("order_type", _NO_ORDER_TEXT) == _NO_ORDER_TEXT:
            return

        entry = decision.get("entry_price")
        if entry is None:
            return
        try:
            entry_f = float(entry)
        except (TypeError, ValueError):
            return

        n = len(frame.bars)
        if n == 0:
            return

        long = is_long_direction(decision.get("order_direction"))
        if long is True:
            symbol, color = "▲", (63, 185, 80)
            anchor = (0.5, 1.0)
        elif long is False:
            symbol, color = "▼", (248, 81, 73)
            anchor = (0.5, 0.0)
        else:
            return

        x_pos = float(n - 1)
        marker = pg.TextItem(
            text=symbol,
            color=color,
            anchor=anchor,
        )
        from PyQt6.QtGui import QFont

        font = QFont()
        font.setPointSize(14)
        font.setBold(True)
        marker.setFont(font)
        marker.setPos(x_pos, entry_f)
        self.addItem(marker)
        self._direction_items.append(marker)

    def _clear_candles_and_labels(self) -> None:
        """Remove all candle and label items from the plot."""
        for item in self._candle_items:
            self.removeItem(item)
        self._candle_items.clear()

        for item in self._seq_labels:
            self.removeItem(item)
        self._seq_labels.clear()
