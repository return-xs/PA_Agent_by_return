"""Verify user diagnosis stats on pending records."""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path


def ans(traces, nid):
    for t in reversed(traces or []):
        if isinstance(t, dict) and str(t.get("node_id")) == nid:
            return t.get("answer")
    return None


def main() -> None:
    files = sorted(Path("records/pending").glob("*.json"))
    n = len(files)

    order_types = Counter()
    t90_no_order = 0
    t90_no_but_order = 0
    watch_limit = 0
    reasoning_limit = 0
    strong_bg_wait = 0

    channels = {"broad_channel", "normal_channel", "tight_channel", "trending_tr"}
    spikes = {"spike", "micro_channel"}

    for fp in files:
        d = json.loads(fp.read_text(encoding="utf-8"))
        s1 = d.get("stage1_diagnosis") or {}
        s2 = d.get("stage2_decision") or {}
        dec = s2.get("decision") or {}
        ot = dec.get("order_type") or "missing"
        order_types[ot] += 1

        dt = s2.get("decision_trace") or []
        a90 = ans(dt, "9.0")
        is_order = ot in ("限价单", "突破单", "市价单")
        if a90 in ("否", "等待"):
            if is_order:
                t90_no_but_order += 1
            else:
                t90_no_order += 1

        wp = " ".join(str(x) for x in (dec.get("watch_points") or []))
        if re.search(r"限价|limit|挂", wp, re.I):
            watch_limit += 1

        rs = str(dec.get("reasoning") or "")
        if re.search(r"限价", rs):
            reasoning_limit += 1

        term = (s2.get("terminal") or {}).get("outcome")
        cycle = s1.get("cycle_position") or ""
        direction = s1.get("direction") or ""
        if term == "wait" and direction in ("bullish", "bearish"):
            if cycle in channels | spikes:
                strong_bg_wait += 1

    print(f"n={n}")
    print("order_types:", dict(order_types))
    print(f"9.0=否/等待 + 不下单: {t90_no_order}")
    print(f"9.0=否/等待 + 有下单: {t90_no_but_order}")
    print(f"watch_points 含限价: {watch_limit}")
    print(f"reasoning 含限价: {reasoning_limit}")
    print(f"通道/尖峰+方向明确+wait: {strong_bg_wait}")


if __name__ == "__main__":
    main()
