import json
import glob
import os
from pathlib import Path

root = Path(__file__).resolve().parents[1]
for p in sorted(glob.glob(str(root / "records/pending/*.json"))):
    with open(p, encoding="utf-8") as f:
        d = json.load(f)
    print("=" * 80)
    print(os.path.basename(p))
    print("partial_reason:", d.get("_partial_reason"))
    print("exception:", d.get("exception"))
    s2m = d.get("stage2_messages") or []
    print("stage2_messages count:", len(s2m))
    for i, m in enumerate(s2m):
        role = m.get("role")
        content = str(m.get("content", ""))
        preview = content[:180].replace("\n", " ")
        print(f"  [{i}] {role} len={len(content)}: {preview!r}")
        if role == "user" and ("校验" in content or "重试" in content or "validation" in content.lower()):
            print("    --- RETRY USER TURN (first 1200 chars) ---")
            print(content[:1200])
            print("    --- end ---")
    dec = d.get("stage2_decision") or {}
    decision = dec.get("decision") or {}
    print("order_type:", decision.get("order_type"))
    print("terminal:", dec.get("terminal"))
