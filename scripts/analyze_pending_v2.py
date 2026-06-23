"""Analyze current pending records vs pre-9.0P baseline."""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path


def ans(traces, nid):
    for t in reversed(traces or []):
        if isinstance(t, dict) and str(t.get("node_id")) == nid:
            return t.get("answer")
    return None


def has_node(traces, nid):
    if not traces:
        return False
    return any(isinstance(t, dict) and str(t.get("node_id")) == nid for t in traces)


def main() -> None:
    pending = Path("records/pending")
    files = sorted(pending.glob("*.json"))
    print(f"Total records: {len(files)}")

    stats = Counter()
    exceptions = []
    order_types = Counter()
    terminal_nodes = Counter()
    fail_nodes = Counter()
    s90_no_order = 0
    s90_order = 0
    s90p_yes = 0
    s90p_no = 0
    s90p_missing_when_90_no = 0
    s90_no_s90p_yes_order = 0
    s90_no_s90p_yes_no_order = 0
    three_price_when_90p = 0

    for fp in files:
        d = json.loads(fp.read_text(encoding="utf-8"))
        meta = d.get("meta") or {}
        stats["stance_" + str(meta.get("decision_stance", "?"))] += 1

        exc = d.get("exception")
        if exc:
            stats["has_exception"] += 1
            exceptions.append(
                {
                    "file": fp.name,
                    "type": exc.get("type") if isinstance(exc, dict) else type(exc).__name__,
                    "stage": exc.get("stage") if isinstance(exc, dict) else None,
                    "message": (exc.get("message") or str(exc))[:200] if isinstance(exc, dict) else str(exc)[:200],
                    "category": exc.get("category") if isinstance(exc, dict) else None,
                    "invalid_fields": exc.get("invalid_fields") if isinstance(exc, dict) else None,
                }
            )

        s1 = d.get("stage1_diagnosis") or {}
        s2 = d.get("stage2_decision") or {}
        if not s2:
            stats["no_stage2"] += 1
            continue

        dec = s2.get("decision") or {}
        ot = dec.get("order_type") or "missing"
        order_types[ot] += 1
        is_order = ot in ("限价单", "突破单", "市价单")

        dt = s2.get("decision_trace") or []
        a90 = ans(dt, "9.0")
        a90p = ans(dt, "9.0P")

        if a90 in ("否", "等待"):
            if is_order:
                s90_order += 1
            else:
                s90_no_order += 1
            if not has_node(dt, "9.0P"):
                s90p_missing_when_90_no += 1
            elif a90p == "是":
                s90p_yes += 1
                if dec.get("entry_price") is not None:
                    three_price_when_90p += 1
                if is_order:
                    s90_no_s90p_yes_order += 1
                else:
                    s90_no_s90p_yes_no_order += 1
            elif a90p in ("否", "等待"):
                s90p_no += 1
        elif a90 == "是":
            stats["s90_yes"] += 1

        term = s2.get("terminal") or {}
        terminal_nodes[str(term.get("node_id"))] += 1
        stats["outcome_" + str(term.get("outcome"))] += 1

        if ot == "不下单":
            for nid in ("9.0P", "9.0", "10.1", "10.2", "10.3", "6.3", "6.4", "14", "14.1"):
                a = ans(dt, nid)
                if a in ("否", "等待"):
                    fail_nodes[nid] += 1
                    break

    n = len(files)
    print("\n=== Order types ===")
    for k, v in order_types.most_common():
        print(f"  {k}: {v} ({100*v/max(n,1):.1f}%)")

    print("\n=== §9.0 / §9.0P (post-reform) ===")
    print(f"  §9.0=否/等待 + 不下单: {s90_no_order}")
    print(f"  §9.0=否/等待 + 有下单: {s90_order}  (baseline was 0/219)")
    print(f"  §9.0=否 且写了 §9.0P=是: {s90p_yes}")
    print(f"  §9.0=否 且 §9.0P=否/等待: {s90p_no}")
    print(f"  §9.0=否 但缺 §9.0P 节点: {s90p_missing_when_90_no}")
    print(f"  §9.0=否 + §9.0P=是 + 有三价(entry): {three_price_when_90p}")
    print(f"  §9.0=否 + §9.0P=是 + 下单: {s90_no_s90p_yes_order}")
    print(f"  §9.0=否 + §9.0P=是 + 仍不下单: {s90_no_s90p_yes_no_order}")

    print("\n=== Terminal nodes (no-order fail) ===")
    for k, v in fail_nodes.most_common(12):
        print(f"  {k}: {v}")

    print("\n=== Terminal node_id (all) ===")
    for k, v in terminal_nodes.most_common(12):
        print(f"  {k}: {v}")

    print("\n=== Outcomes ===")
    for k, v in sorted((k for k in stats if k.startswith("outcome_")), key=lambda x: stats[x], reverse=True):
        print(f"  {k.replace('outcome_', '')}: {stats[k]}")

    print(f"\n=== Exceptions: {stats.get('has_exception', 0)} ===")
    for e in exceptions:
        print(f"  [{e['file']}] stage={e['stage']} cat={e['category']}")
        print(f"    {e['message']}")
        if e.get("invalid_fields"):
            print(f"    invalid: {e['invalid_fields'][:5]}")


if __name__ == "__main__":
    main()
