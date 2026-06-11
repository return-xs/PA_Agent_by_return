"""Detect stage-2 order opportunities and format alert text."""
from __future__ import annotations

import logging
import os
import sys
from typing import Any

logger = logging.getLogger(__name__)

ORDER_OPPORTUNITY_TYPES: frozenset[str] = frozenset({"限价单", "突破单", "市价单"})


def has_order_opportunity(decision: dict[str, Any] | None) -> bool:
    """Return True when stage-2 decision proposes an actual order."""
    if not isinstance(decision, dict):
        return False
    return str(decision.get("order_type") or "") in ORDER_OPPORTUNITY_TYPES


def _fmt_price(value: Any) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):g}"
    except (TypeError, ValueError):
        return str(value)


def format_order_alert_message(decision: dict[str, Any]) -> str:
    """Short summary for the order-opportunity popup."""
    direction = decision.get("order_direction") or "—"
    order_type = decision.get("order_type") or "—"
    entry = _fmt_price(decision.get("entry_price"))
    stop = _fmt_price(decision.get("stop_loss_price"))
    target = _fmt_price(decision.get("take_profit_price"))
    reasoning = str(decision.get("reasoning") or "").strip()
    lines = [
        f"方向：{direction}",
        f"方式：{order_type}",
        f"入场：{entry}",
        f"止损：{stop}",
        f"止盈：{target}",
    ]
    if reasoning:
        preview = reasoning if len(reasoning) <= 200 else reasoning[:200] + "…"
        lines.append("")
        lines.append(preview)
    lines.append("")
    lines.append("已切换到「决策」页，请核对详情。")
    return "\n".join(lines)


def _windows_alert_wav_paths() -> list[str]:
    media = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Media")
    names = (
        "notify.wav",
        "Windows Notify.wav",
        "Alarm01.wav",
        "Windows Exclamation.wav",
    )
    return [os.path.join(media, name) for name in names]


def play_order_alert_sound() -> bool:
    """Play a short alert sound (best-effort). Returns True if playback was attempted."""
    if sys.platform == "win32":
        import winsound

        for path in _windows_alert_wav_paths():
            if not os.path.isfile(path):
                continue
            try:
                # Blocking playback: MessageBeep often returns instantly with no audible output.
                winsound.PlaySound(path, winsound.SND_FILENAME)
                return True
            except Exception as exc:
                logger.debug("order alert PlaySound file %s failed: %s", path, exc)

        for alias in ("SystemExclamation", "SystemHand", "SystemAsterisk"):
            try:
                winsound.PlaySound(alias, winsound.SND_ALIAS | winsound.SND_NODEFAULT)
                return True
            except Exception as exc:
                logger.debug("order alert PlaySound alias %s failed: %s", alias, exc)

        try:
            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
            return True
        except Exception as exc:
            logger.debug("order alert MessageBeep failed: %s", exc)

    try:
        from PyQt6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is not None:
            app.beep()
            return True
    except Exception as exc:
        logger.debug("order alert QApplication.beep failed: %s", exc)

    return False
