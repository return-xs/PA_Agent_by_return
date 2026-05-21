"""E2E smoke test — no-order path: stage2 returns 不下单.

Task 19.2
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
import pyqtgraph as pg

from pa_agent.data.base import KlineBar
from pa_agent.data.kline_buffer import KlineBuffer
from pa_agent.app_context import AppContext
from pa_agent.ai.json_validator import JsonValidator
from pa_agent.ai.router import route_strategy_files

from tests.fixtures.ai_payloads import VALID_STAGE1, VALID_STAGE2_NO_ORDER


def _make_reply(content_dict: dict) -> MagicMock:
    reply = MagicMock()
    reply.content = json.dumps(content_dict)
    reply.raw = {"content": reply.content}
    reply.usage = MagicMock()
    reply.usage.prompt_tokens = 100
    reply.usage.completion_tokens = 50
    reply.usage.cached_prompt_tokens = 0
    reply.usage.total_tokens = 150
    return reply


def _make_ctx(tmp_path):
    """Build a minimal AppContext configured for a no-order response."""
    buffer = KlineBuffer(capacity=500)
    for i in range(10, 0, -1):
        bar = KlineBar(
            seq=i,
            ts_open=1_700_000_000_000 - i * 3_600_000,
            open=2000.0,
            high=2010.0,
            low=1990.0,
            close=2005.0,
            volume=100.0,
            closed=(i > 1),
        )
        if i == 1:
            buffer.update_forming(bar)
        else:
            buffer.append(bar)

    mock_client = MagicMock()
    mock_client.stream_chat.side_effect = [
        _make_reply(VALID_STAGE1),
        _make_reply(VALID_STAGE2_NO_ORDER),
    ]

    mock_assembler = MagicMock()
    mock_assembler.build_stage1.return_value = [{"role": "system", "content": "s1"}]
    mock_assembler.build_stage2.return_value = [{"role": "system", "content": "s2"}]

    pending_writer = MagicMock()

    ctx = AppContext()
    ctx.buffer = buffer
    ctx.client = mock_client
    ctx.assembler = mock_assembler
    ctx.router = route_strategy_files
    ctx.validator = JsonValidator()
    ctx.pending_writer = pending_writer
    ctx.exp_reader = MagicMock()
    ctx.exp_reader.read_top5.return_value = []

    return ctx, pending_writer


@pytest.mark.e2e
def test_no_order_shows_no_trade_conclusion(qtbot, tmp_path):
    """When stage2 returns 不下单, DecisionPanel shows that conclusion."""
    from pa_agent.gui.main_window import MainWindow

    ctx, pending_writer = _make_ctx(tmp_path)

    window = MainWindow(ctx)
    qtbot.addWidget(window)
    window.show()

    window._bar_count_spin.setValue(5)
    window._on_submit_analysis()

    # Poll until the analysis is no longer in progress
    qtbot.waitUntil(
        lambda: not window._analysis_in_progress,
        timeout=10_000,
    )

    # DecisionPanel should show 不下单
    conclusion_text = window._decision_panel._conclusion_label.text()
    assert "不下单" in conclusion_text, (
        f"Expected 不下单 conclusion, got: {conclusion_text!r}"
    )

    # Chart should have no InfiniteLine items (no entry/TP/SL lines)
    chart = window._chart_widget
    infinite_lines = [
        item for item in chart.items()
        if isinstance(item, pg.InfiniteLine)
    ]
    assert len(infinite_lines) == 0, (
        f"Expected no InfiniteLine items for 不下单, found {len(infinite_lines)}"
    )
