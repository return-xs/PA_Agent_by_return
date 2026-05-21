"""Run once: python fix_garbage_line.py  (from D:\\cl\\PA_Agent)"""
import re
from pathlib import Path

p = Path(__file__).resolve().parent / "prompt_engineering" / "极速上涨交易策略.txt"
text = p.read_text(encoding="utf-8")
text = re.sub(r"\ufffd+", "", text)
lines = [ln for ln in text.splitlines() if ln.strip() != "UNIQUE_SL3_TYPE"]
for i, ln in enumerate(lines):
    if "止损类型3" in ln and ln.strip() != "止损类型3：技术位止损":
        lines[i] = "止损类型3：技术位止损"
p.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("fixed", p)
