"""Scan records/pending for validation retries."""
from __future__ import annotations

import json
from pathlib import Path


def retry_info(msgs: list[dict]) -> tuple[int, list[str]]:
    assistants = sum(1 for m in msgs if m.get("role") == "assistant")
    feedbacks: list[str] = []
    for m in msgs:
        if m.get("role") != "user":
            continue
        c = str(m.get("content", ""))
        if "校验未通过" in c:
            feedbacks.append(c)
    return assistants, feedbacks


def main() -> None:
    pending = Path("records/pending")
    rows: list[dict] = []
    for p in sorted(pending.glob("*.json")):
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        meta = d.get("meta", {})
        exc = d.get("exception")
        s1 = d.get("stage1_messages") or []
        s2 = d.get("stage2_messages") or []
        a1, fb1 = retry_info(s1)
        a2, fb2 = retry_info(s2)
        decision = (d.get("stage2_decision") or {}).get("decision") or {}
        terminal = (d.get("stage2_decision") or {}).get("terminal") or {}
        rows.append(
            {
                "file": p.name,
                "sym": meta.get("symbol"),
                "s1_asst": a1,
                "s1_retry": len(fb1),
                "s2_asst": a2,
                "s2_retry": len(fb2),
                "fb1": fb1,
                "fb2": fb2,
                "exc": (exc or {}).get("message") if exc else None,
                "order": decision.get("order_type"),
                "terminal": terminal.get("outcome"),
            }
        )

    print("file | s1_asst | s1_retry | s2_asst | s2_retry | order | terminal | exc")
    for r in rows:
        exc_short = (r["exc"] or "")[:40]
        print(
            f"{r['file'][:38]:38} | {r['s1_asst']} | {r['s1_retry']} | "
            f"{r['s2_asst']} | {r['s2_retry']} | {r['order']} | {r['terminal']} | {exc_short}"
        )

    print("\n=== Validation retries (校验未通过) ===")
    found = False
    for r in rows:
        if r["s1_retry"] or r["s2_retry"]:
            found = True
            print(f"\n--- {r['file']} ---")
            for fb in r["fb1"] + r["fb2"]:
                for line in fb.splitlines():
                    s = line.strip()
                    if not s:
                        continue
                    if s.startswith("-") or "category" in s or "必须" in s or "错误" in s:
                        print(" ", s[:220])

    if not found:
        print("(none)")

    print("\n=== Stage2 multi-assistant (retry if >1) ===")
    found2 = False
    for r in rows:
        if r["s2_asst"] > 1:
            found2 = True
            print(r["file"], r)
    if not found2:
        print("(none)")

    print("\n=== Provider / partial failures (non-credit excluded below) ===")
    for r in rows:
        if not r["exc"]:
            continue
        if r["exc"] and "积分" in r["exc"]:
            continue
        print(r["file"], r["exc"])


if __name__ == "__main__":
    main()
