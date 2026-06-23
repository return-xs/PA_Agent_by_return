"""Detail: planned-limit path failures in pending records."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path


def ans(traces: list | None, nid: str) -> str | None:
    for t in reversed(traces or []):
        if isinstance(t, dict) and str(t.get("node_id")) == nid:
            return t.get("answer")
    return None


def reason9(traces: list | None) -> str:
    for t in traces or []:
        if isinstance(t, dict) and str(t.get("node_id")) == "9.0":
            return str(t.get("reason") or "")[:90]
    return ""


def main() -> None:
    files = sorted(Path("records/pending").glob("*.json"))
    planned_fail = Counter()
    planned_order = 0
    no90_null = Counter()
    no90_has = Counter()

    for fp in files:
        d = json.loads(fp.read_text(encoding="utf-8"))
        s2 = d.get("stage2_decision") or {}
        sb = (s2.get("bar_analysis") or {}).get("signal_bar") or {}
        sb_null = sb.get("bar") is None
        dt = s2.get("decision_trace") or []
        a90 = ans(dt, "9.0")
        ot = (s2.get("decision") or {}).get("order_type")

        if sb_null and a90 == "否":
            no90_null[reason9(dt) or "(empty)"] += 1
        if (not sb_null) and a90 == "否":
            no90_has[reason9(dt) or "(empty)"] += 1

        if not (sb_null and a90 == "是"):
            continue
        if ot in ("限价单", "突破单", "市价单"):
            planned_order += 1
            continue
        for nid in ("6.3", "6.4", "10.1", "10.2", "10.3", "14", "14.1"):
            a = ans(dt, nid)
            if a in ("否", "等待"):
                planned_fail[nid] += 1
                break
        else:
            planned_fail[str((s2.get("terminal") or {}).get("node_id"))] += 1

    print("null signal + 9.0=是:")
    print("  orders:", planned_order)
    print("  no-order fail at:", dict(planned_fail))
    print("\n9.0=否 + null signal (top 12):")
    for k, v in no90_null.most_common(12):
        print(f"  [{v}] {k}")
    print("\n9.0=否 + HAS signal (top 8):")
    for k, v in no90_has.most_common(8):
        print(f"  [{v}] {k}")


if __name__ == "__main__":
    main()
