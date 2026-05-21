"""Risk/reward and estimated win-rate helpers for trading decisions."""
from __future__ import annotations

from typing import Any


def is_long_direction(direction: object) -> bool | None:
    """Return True for long, False for short, None if unknown."""
    text = str(direction or "").strip().lower()
    if not text:
        return None
    if "多" in text or text in ("long", "buy", "bull"):
        return True
    if "空" in text or text in ("short", "sell", "bear"):
        return False
    return None


def compute_risk_reward(
    entry: object,
    take_profit: object,
    stop_loss: object,
    direction: object,
) -> dict[str, float | str] | None:
    """Compute risk/reward distances and reward:risk ratio (盈亏比).

    Returns None when prices are invalid or risk is zero.
    """
    try:
        e = float(entry)
        tp = float(take_profit)
        sl = float(stop_loss)
    except (TypeError, ValueError):
        return None

    long = is_long_direction(direction)
    if long is True:
        risk = e - sl
        reward = tp - e
    elif long is False:
        risk = sl - e
        reward = e - tp
    else:
        if tp > e and sl < e:
            risk = e - sl
            reward = tp - e
        elif tp < e and sl > e:
            risk = sl - e
            reward = e - tp
        else:
            return None

    if risk <= 0 or reward <= 0:
        return None

    ratio = reward / risk
    return {
        "risk": risk,
        "reward": reward,
        "ratio": ratio,
        "ratio_text": f"{ratio:.2f} : 1",
    }


def format_estimated_win_rate(decision: dict[str, Any]) -> str | None:
    """Format model-provided estimated_win_rate (0–100) for display."""
    value = decision.get("estimated_win_rate")
    if value is None or value == "":
        return None
    try:
        pct = max(0, min(100, int(float(str(value).strip()))))
    except (ValueError, TypeError):
        return None
    return f"{pct}%"


def format_estimated_win_rate_reasoning(decision: dict[str, Any]) -> str:
    return str(decision.get("estimated_win_rate_reasoning", "") or "").strip()
