"""Normalize common Stage 2 AI JSON variants before schema validation."""
from __future__ import annotations

import copy
import logging
from typing import Any

from pa_agent.ai.trace_normalize import normalize_stage2_traces
from pa_agent.util.price_tick import normalize_breakout_entry_price

logger = logging.getLogger(__name__)


def _normalize_next_bar_prediction(prediction: dict[str, Any]) -> None:
    """In-place normalize next_bar_prediction common model quirks. Idempotent."""
    if not isinstance(prediction, dict):
        return

    # 1. unpredictable fallback
    unpredictable = bool(prediction.get("unpredictable", False))
    prediction["unpredictable"] = unpredictable

    # 2. features_used: ensure list, dedup, minimum set
    feats = prediction.get("features_used")
    if not isinstance(feats, list):
        feats = []
    feats = [f for f in feats if isinstance(f, str)]
    if "stage1_diagnosis" not in feats:
        feats.insert(0, "stage1_diagnosis")
    seen: set[str] = set()
    deduped: list[str] = []
    for f in feats:
        if f not in seen:
            deduped.append(f)
            seen.add(f)
    prediction["features_used"] = deduped

    # 3. reasoning truncation (R7.6)
    reasoning = prediction.get("reasoning")
    if isinstance(reasoning, str) and len(reasoning) > 1500:
        prediction["reasoning"] = reasoning[:1499] + "…"
    elif not isinstance(reasoning, str):
        prediction["reasoning"] = ""

    if unpredictable:
        # unpredictable → force direction / probabilities = null
        prediction["direction"] = None
        prediction["probabilities"] = None
        return

    # 4. probabilities integer rounding (R3.1)
    probs = prediction.get("probabilities")
    if isinstance(probs, dict):
        normalized: dict[str, int] = {}
        for key in ("bullish", "bearish", "neutral"):
            raw = probs.get(key)
            try:
                value = int(round(float(raw))) if raw is not None else 0
            except (TypeError, ValueError):
                value = 0
            normalized[key] = max(0, min(100, value))
        prediction["probabilities"] = normalized

        # 5. direction = argmax (R3.3, break ties by literal order)
        order = ("bullish", "bearish", "neutral")
        max_value = max(normalized[k] for k in order)
        prediction["direction"] = next(k for k in order if normalized[k] == max_value)
    # else: unparseable probabilities with unpredictable=False — leave for validator


def _max_bar_seq_from_frame(kline_frame: Any) -> int | None:
    bars = getattr(kline_frame, "bars", None) if kline_frame is not None else None
    if not bars:
        return None
    seqs = [int(getattr(b, "seq", 0)) for b in bars if getattr(b, "seq", None)]
    return max(seqs) if seqs else None


def normalize_stage2(
    obj: dict[str, Any],
    *,
    normalization_mode: str = "strict",
    kline_frame: Any = None,
) -> dict[str, Any]:
    """Return a copy of *obj* with decision_trace quirks corrected."""
    out = copy.deepcopy(obj)
    frame_max = _max_bar_seq_from_frame(kline_frame)
    normalize_stage2_traces(
        out,
        normalization_mode=normalization_mode,
        default_max_seq=frame_max,
    )
    decision = out.get("decision")
    if isinstance(decision, dict) and normalize_breakout_entry_price(
        decision, kline_frame=kline_frame
    ):
        logger.debug(
            "breakout entry_price adjusted to basis extreme ± 1 tick (basis=%s)",
            decision.get("entry_basis_bar"),
        )
    if isinstance(decision, dict) and decision.get("order_type") == "不下单":
        # A no-order decision has no executable trade; tolerate model-provided
        # win-rate estimates in legacy payloads by clearing them before schema
        # validation while keeping price-field mistakes strict.
        decision["estimated_win_rate"] = None

    bar_analysis = out.get("bar_analysis")
    if isinstance(bar_analysis, dict):
        signal_bar = bar_analysis.get("signal_bar")
        if isinstance(signal_bar, dict) and not signal_bar.get("bar"):
            signal_bar["bar"] = None
            signal_bar.setdefault("quality", "invalid")
            signal_bar.setdefault("pattern", "none")

        entry_bar = bar_analysis.get("entry_bar")
        if isinstance(entry_bar, dict):
            strength = str(entry_bar.get("strength", "") or "").strip().lower()
            has_bar = bool(entry_bar.get("bar"))
            if strength == "not_triggered" or not has_bar:
                # Pending limit/breakout orders do not have an actual entry bar
                # yet. Normalize common model variants before schema checks.
                entry_bar["strength"] = "not_triggered"
                entry_bar.setdefault("bar", None)
                entry_bar.setdefault("freshness", "pending")
                if entry_bar.get("follow_through") in (None, "", "pending"):
                    entry_bar["follow_through"] = "pending"

    # Next bar prediction normalization (R8.6: only when field exists)
    pred = out.get("next_bar_prediction")
    if isinstance(pred, dict):
        _normalize_next_bar_prediction(pred)

    return out
