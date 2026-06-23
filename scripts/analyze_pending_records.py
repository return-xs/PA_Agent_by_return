"""One-off analysis of records/pending/*.json."""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path


def trace_answer(traces: list | None, node_id: str) -> str | None:
    if not traces:
        return None
    for t in reversed(traces):
        if isinstance(t, dict) and str(t.get("node_id")) == node_id:
            return t.get("answer")
    return None


def trace_reason_snip(traces: list | None, node_id: str, n: int = 80) -> str:
    if not traces:
        return ""
    for t in reversed(traces):
        if isinstance(t, dict) and str(t.get("node_id")) == node_id:
            return str(t.get("reason") or "")[:n]
    return ""


def main() -> None:
    pending = Path("records/pending")
    files = sorted(pending.glob("*.json"))
    print(f"Total records: {len(files)}")

    stats: dict = {
        "order_type": Counter(),
        "stance": Counter(),
        "gate_result": Counter(),
        "s1_signal_bar_null": 0,
        "s2_signal_bar_null": 0,
        "s2_signal_quality": Counter(),
        "terminal_outcome": Counter(),
        "exception": 0,
        "no_s2": 0,
    }

    no_order_terminal: Counter = Counter()
    no_order_90: Counter = Counter()
    signal_null_no_order = 0
    signal_null_order = 0
    signal_present_no_order = 0
    signal_present_order = 0
    s90_when_null: Counter = Counter()
    fail_node: Counter = Counter()
    cycle_order: dict[str, Counter] = defaultdict(Counter)
    no_order_reasons: Counter = Counter()
    planned_limit_attempts = 0  # 9.0=是 + null signal + 不下单 vs order

    for fp in files:
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            stats["exception"] += 1
            continue

        meta = data.get("meta") or {}
        stats["stance"][meta.get("decision_stance") or "unknown"] += 1
        if data.get("exception"):
            stats["exception"] += 1

        s1 = data.get("stage1_diagnosis") or {}
        s2 = data.get("stage2_decision") or {}
        if not s2:
            stats["no_s2"] += 1
            continue

        gr = s1.get("gate_result") or "missing"
        stats["gate_result"][gr] += 1

        s1_sb = (s1.get("bar_analysis") or {}).get("signal_bar") or {}
        if s1_sb.get("bar") is None:
            stats["s1_signal_bar_null"] += 1

        s2_sb = (s2.get("bar_analysis") or {}).get("signal_bar") or {}
        s2_sb_null = s2_sb.get("bar") is None
        if s2_sb_null:
            stats["s2_signal_bar_null"] += 1
        q = s2_sb.get("quality")
        if q:
            stats["s2_signal_quality"][str(q)] += 1

        dec = s2.get("decision") or {}
        ot = dec.get("order_type") or "missing"
        stats["order_type"][ot] += 1
        cycle_order[s1.get("cycle_position") or "unknown"][ot] += 1

        term = s2.get("terminal") or {}
        stats["terminal_outcome"][str(term.get("outcome"))] += 1

        dt = s2.get("decision_trace") or []
        a90 = trace_answer(dt, "9.0")

        if s2_sb_null:
            s90_when_null[str(a90)] += 1

        is_order = ot in ("限价单", "突破单", "市价单")
        if s2_sb_null:
            if is_order:
                signal_null_order += 1
            else:
                signal_null_no_order += 1
        else:
            if is_order:
                signal_present_order += 1
            else:
                signal_present_no_order += 1

        if s2_sb_null and a90 == "是":
            planned_limit_attempts += 1

        if ot == "不下单":
            no_order_terminal[str(term.get("node_id"))] += 1
            no_order_90[str(a90)] += 1
            for nid in ("9.0", "10.1", "10.2", "10.3", "14", "14.1"):
                ans = trace_answer(dt, nid)
                if ans in ("否", "等待") and nid in ("9.0", "10.1", "10.2", "10.3"):
                    fail_node[nid] += 1
                    break
                if nid.startswith("14") and ans == "是":
                    fail_node[nid] += 1
                    break
            else:
                fail_node[str(term.get("node_id"))] += 1

            rs = trace_reason_snip(dt, str(term.get("node_id")))
            if not rs:
                rs = (
                    trace_reason_snip(dt, "9.0")
                    or trace_reason_snip(dt, "10.3")
                    or trace_reason_snip(dt, "10.2")
                )
            no_order_reasons[rs[:60] if rs else "unknown"] += 1

    n = len(files)
    print("\n=== Order types ===")
    for k, v in stats["order_type"].most_common():
        print(f"  {k}: {v} ({100 * v / n:.1f}%)")

    print("\n=== Stance ===")
    for k, v in stats["stance"].most_common():
        print(f"  {k}: {v}")

    print("\n=== Stage1 gate_result ===")
    for k, v in stats["gate_result"].most_common():
        print(f"  {k}: {v}")

    print(f"\nStage1 signal_bar.bar=null: {stats['s1_signal_bar_null']} / {n}")
    print(f"Stage2 signal_bar.bar=null: {stats['s2_signal_bar_null']} / {n}")
    print("Stage2 signal quality:", dict(stats["s2_signal_quality"]))

    print("\n=== Signal bar null vs order ===")
    print(f"  null signal + order: {signal_null_order}")
    print(f"  null signal + no order: {signal_null_no_order}")
    print(f"  has signal + order: {signal_present_order}")
    print(f"  has signal + no order: {signal_present_no_order}")
    print(f"  null signal + §9.0=是 (planned limit path tried): {planned_limit_attempts}")

    print("\n=== §9.0 when signal_bar.bar=null ===")
    for k, v in s90_when_null.most_common():
        print(f"  {k}: {v}")

    print("\n=== No-order: first fail node ===")
    for k, v in fail_node.most_common(15):
        print(f"  {k}: {v}")

    print("\n=== No-order: terminal node ===")
    for k, v in no_order_terminal.most_common(15):
        print(f"  {k}: {v}")

    print("\n=== No-order: §9.0 answer ===")
    for k, v in no_order_90.most_common():
        print(f"  {k}: {v}")

    print("\n=== Terminal outcomes ===")
    for k, v in stats["terminal_outcome"].most_common():
        print(f"  {k}: {v}")

    print("\n=== Cycle x order ===")
    for cycle in sorted(cycle_order.keys()):
        c = cycle_order[cycle]
        total = sum(c.values())
        orders = sum(c.get(x, 0) for x in ("限价单", "突破单", "市价单"))
        pct = 100 * orders / total if total else 0
        print(f"  {cycle}: orders={orders}/{total} ({pct:.0f}%) | {dict(c)}")

    print("\n=== Top no-order reason snippets ===")
    for k, v in no_order_reasons.most_common(15):
        print(f"  [{v}] {k}")


if __name__ == "__main__":
    main()
