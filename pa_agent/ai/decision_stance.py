"""Trading decision stance profiles for Stage 2 prompt injection."""
from __future__ import annotations

from typing import Literal

DecisionStance = Literal["conservative", "balanced", "aggressive", "extreme_aggressive"]

STANCE_LABELS_ZH: dict[str, str] = {
    "conservative": "保守",
    "balanced": "均衡",
    "aggressive": "激进",
    "extreme_aggressive": "极度激进",
}

_STANCE_ALIASES: dict[str, DecisionStance] = {
    "conservative": "conservative",
    "保守": "conservative",
    "balanced": "balanced",
    "均衡": "balanced",
    "aggressive": "aggressive",
    "激进": "aggressive",
    "extreme_aggressive": "extreme_aggressive",
    "extreme": "extreme_aggressive",
    "极度激进": "extreme_aggressive",
}


def normalize_stance(value: str | None) -> DecisionStance:
    """Coerce settings/UI value to a known stance id."""
    if not value:
        return "conservative"
    key = str(value).strip().lower()
    if key in _STANCE_ALIASES:
        return _STANCE_ALIASES[key]
    raw = str(value).strip()
    if raw in _STANCE_ALIASES:
        return _STANCE_ALIASES[raw]
    return "conservative"


def stance_label_zh(stance: str | None) -> str:
    """Return Chinese label for UI."""
    return STANCE_LABELS_ZH.get(normalize_stance(stance), "保守")


def build_decision_stance_guidance(stance: str | None) -> str:
    """Return Stage-2-only guidance block for the current trading stance."""
    normalized = normalize_stance(stance)
    label = stance_label_zh(normalized)

    common_rules = (
        "通用约束（各档都必须遵守）：\n"
        "- 仍必须完整输出 decision_trace，按 §9–§11、§14 走适用节点，不得伪造 trace。\n"
        "- 节点 10.3 须基于已拟定的 entry/stop/target 做数值判断；禁止无止损、无目标。\n"
        "- 完成 10.3 后必须在 decision 中填写 estimated_win_rate（0–100）与 estimated_win_rate_reasoning。\n"
        "- order_type 与 terminal.outcome 必须一致（有下单 → outcome=trade）。\n"
        "- 触犯 §14 硬性禁止项时，极度激进档也允许 order_type=不下单，"
        "但须在 reasoning 明确写出触犯的条款。\n"
    )

    if normalized == "conservative":
        profile = (
            "【保守】= 当前系统默认裁定标准（与改版前一致）。\n"
            "- §9 入场：优先典型、清晰、收盘确认的一类信号；次优/模糊 setup 默认继续等待。\n"
            "- §10：止损必须明确且不过大；10.3 交易者方程边际情况倾向判「否」。"
            "风险回报比倾向要求 ≥ 1.5:1 才更易通过。\n"
            "- §14：从严扫描；有疑虑即不下单。\n"
            "- trade_confidence：40–59 或结构存在明显歧义时，优先 order_type=不下单。\n"
            "- 交易区间中部、方向中性、信号棒质量一般时，默认观望。\n"
        )
    elif normalized == "balanced":
        profile = (
            "【均衡】= 在遵守决策树的前提下，比【保守】更愿意执行交易。\n"
            "- §9 入场：除典型信号外，若结构与阶段一 direction/cycle_position 一致，"
            "允许「次优但可执行」的二类 setup（须在 reason 中写明为何仍值得做）。\n"
            "- §10：10.3 边际可通过时，若胜率×回报与败率×风险大致相当且结构清晰，可判「是」；"
            "可接受约 1.2:1 的风险回报比，但须在 trade_confidence_reasoning 写明假设。\n"
            "- §14：仅明确触犯才不下单；不要因「不够完美」单独放弃。\n"
            "- trade_confidence：35–49 且入场逻辑完整时，可给出下单方案（在 reasoning 说明风险克制）。\n"
            "- 顺势通道/尖峰延续、区间边界反弹：方向一致时可优先考虑下单，而非默认等待。\n"
        )
    elif normalized == "aggressive":
        profile = (
            "【激进】= 在遵守决策树的前提下，比【均衡】更愿意执行交易。\n"
            "- §9 入场：结构方向一致时，可接受更早、更不完美的入场触发；"
            "须在 reason 说明接受的瑕疵与失效条件。\n"
            "- §10：10.3 在 entry/stop/target 已明确时，若方程略偏边际但方向与周期位置一致，"
            "可判「是」；可接受约 1.0:1 的风险回报比，必须在 reasoning 强调风险克制。\n"
            "- §14：仅硬性禁止项触发不下单；不要因为「理想目标位更远」而放弃可执行方案。\n"
            "- trade_confidence：30–44 且逻辑链完整时，仍可输出具体下单类型；"
            "用 watch_points / invalidation_condition 补足不确定性。\n"
            "- 趋势延续、突破回踩、区间边界：只要阶段一 gate_result=proceed，"
            "应主动寻找可下单方案，而不是先找理由观望。\n"
        )
    else:
        profile = (
            "【极度激进】= 本档目标是在结构未触犯 §14 硬性禁止时，"
            "**必须给出具体进场方案**，禁止因犹豫而输出「不下单」。\n"
            "- **强制产出交易**：order_type 必须是「限价单」「突破单」「市价单」之一；"
            "order_direction 必须是「做多」或「做空」，不得为 null。\n"
            "- **强制选定方向**：综合阶段一 direction、HTF、最近 K 线动能与关键位，"
            "在多空之间**必须选一个**更优方向；若阶段一为 neutral，"
            "根据最近 3–5 根已收盘 K 线的净方向与位置（区间上沿/下沿）做出明确选择，"
            "并在 diagnosis_confidence_reasoning 说明为何二选一。\n"
            "- **强制选定方式**：在 §11 中选定一种下单类型并给出具体价格："
            "突破单（顺势突破触发）、限价单（回撤挂单）、市价单（已有明确突破且需立即跟进）。\n"
            "- entry_price、stop_loss_price、take_profit_price 必须全部为有效数值（不可为 null）。\n"
            "- §9：信号不完美也可判「是」，但须在 reason 写明接受的瑕疵；"
            "不得因「等待更好信号」而改判不下单。\n"
            "- §10.3：在止损/目标已设定的前提下，**优先判「是」**；"
            "可基于结构合理估算胜率（允许 45–55% 区间），"
            "方程略偏边际仍可通过，但须在 trade_confidence_reasoning 写明「极度激进强制进场」。\n"
            "- trade_confidence 可低至 25–40，但仍须输出完整下单方案；"
            "风险通过紧凑止损、明确 invalidation_condition 来管理，而非拒绝交易。\n"
            "- **唯一允许不下单的情况**：§14 禁止行为清单中硬性条款明确触犯"
            "（例如数据不足、极端混乱、尖峰中逆势、无止损等）；"
            "此时 terminal.outcome 应为 reject，并在 reasoning 引用具体禁止项。\n"
        )

    return (
        f"## 交易倾向（当前：{label} / {normalized}）\n\n"
        f"{common_rules}\n"
        f"{profile}\n"
        "请在 decision.reasoning 与 trade_confidence_reasoning 中体现本档位如何影响最终裁定。"
    )
