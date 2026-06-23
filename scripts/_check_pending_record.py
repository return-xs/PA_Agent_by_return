"""One-off checker for pending record vs market_features."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pa_agent.ai.market_features import compute_simple_market_features, render_simple_market_features
from pa_agent.ai.pattern_routing import sync_detected_patterns_field
from pa_agent.data.base import KlineBar, KlineFrame
from pa_agent.data.snapshot import compute_indicators


def main() -> None:
    path = Path(r"records/pending/2026-06-22_12-06-00_XAUUSDm_15m.json")
    rec = json.loads(path.read_text(encoding="utf-8"))
    bars = tuple(KlineBar(**b) for b in rec["kline_data"])
    ind = compute_indicators(list(bars))
    frame = KlineFrame(
        symbol=rec["meta"]["symbol"],
        timeframe=rec["meta"]["timeframe"],
        bars=bars,
        indicators=ind,
        snapshot_ts_local_ms=rec["meta"]["timestamp_local_ms"],
    )
    feat = compute_simple_market_features(frame)
    print("=== PROGRAM FEATURES ===")
    print(render_simple_market_features(feat))
    print()
    print("zone", feat.zone, "position", feat.price_position)
    print("barbwire", feat.barbwire_score, feat.barbwire_candidate)
    print("swing", feat.swing_structure, "swing_count", len(feat.swings))
    print("breakout_events", len(feat.breakout_events))
    for e in feat.breakout_events[:8]:
        print(" ", e)
    print("HL", feat.hl_count)
    print("supports", feat.supports[:3])
    print("resistances", feat.resistances[:3])
    print("MM", [(m.kind, m.target_price) for m in feat.measured_moves[:4]])

    for label, key in [("stage1", "stage1_messages"), ("stage2", "stage2_messages")]:
        for i, m in enumerate(rec.get(key) or []):
            content = m.get("content") or ""
            has = "程序结构辅助特征" in content
            print(f"{label}_msg[{i}] role={m.get('role')} market_features={has} chars={len(content)}")

    s1 = dict(rec["stage1_diagnosis"])
    before = list(s1.get("detected_patterns") or [])
    sync_detected_patterns_field(s1)
    print("patterns in record:", before)
    print("patterns after routing sync:", s1["detected_patterns"])
    print("exception:", rec.get("exception"))

    s2 = rec.get("stage2_decision") or {}
    trace = s2.get("decision_trace") or []
    print("stage2 order:", (s2.get("decision") or {}).get("order_type"))
    print("terminal:", s2.get("terminal"))
    print("trace nodes:", [t.get("node_id") for t in trace])


if __name__ == "__main__":
    main()
