"""Unit tests for JSON repair in json_validator."""
from __future__ import annotations

import json
from pathlib import Path

from pa_agent.ai.json_validator import _repair_unescaped_quotes, _strip_fences

_SAMPLE = Path(__file__).resolve().parents[2] / "tools" / "stage2_raw_sample.txt"


def test_stage2_raw_sample_repair_then_parse():
    """Broken stage-2 sample with inner quotes must parse after repair."""
    raw = _SAMPLE.read_text(encoding="utf-8")
    stripped = _strip_fences(raw)
    repaired = _repair_unescaped_quotes(stripped)
    obj = json.loads(repaired)
    assert obj["decision"]["order_type"] == "不下单"
    assert "在区间中部入场" in obj["decision"]["reasoning"]


def test_strip_fences_includes_repair():
    """_strip_fences applies quote repair so json.loads succeeds directly."""
    raw = _SAMPLE.read_text(encoding="utf-8")
    obj = json.loads(_strip_fences(raw))
    assert isinstance(obj["decision_trace"], list)
