"""Conservative market-regime detector for Stock Ultimus."""

from __future__ import annotations

from typing import Any


MARKET_REGIME_DETECTOR_VERSION = "market_regime_detector_v1"
KNOWN_REGIMES = {
    "BULLISH_LOW_VOL",
    "NEUTRAL_RANGE",
    "BEARISH_OR_CORRECTION",
    "HIGH_VOL_EVENT_RISK",
    "INTRADAY_TREND",
    "UNKNOWN",
}


def safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return default
        return float(value)
    except Exception:
        return default


def safe_upper(value: Any, default: str = "UNKNOWN") -> str:
    text = str(value or "").strip().upper()
    return text or default


def explicit_regime(*sources: Any) -> str | None:
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in ["strategy_regime", "market_regime", "regime", "regime_id"]:
            regime = safe_upper(source.get(key), "")
            if regime in KNOWN_REGIMES and regime != "UNKNOWN":
                return regime
    return None


def _technical_votes(technical: dict[str, Any]) -> dict[str, int]:
    votes = {"bullish": 0, "bearish": 0, "neutral": 0, "intraday": 0}
    for item in (technical or {}).values():
        if not isinstance(item, dict):
            continue
        trend = safe_upper(item.get("trend") or item.get("bias") or item.get("technical_bias"), "")
        context = safe_upper(item.get("strategy_context") or item.get("timeframe") or item.get("source"), "")
        score = safe_float(item.get("score") or item.get("technical_score"), None)
        if "INTRADAY" in context or "OPENING_RANGE" in context:
            votes["intraday"] += 1
        if "BULL" in trend or (score is not None and score >= 70):
            votes["bullish"] += 1
        elif "BEAR" in trend or "DOWN" in trend or (score is not None and score <= 35):
            votes["bearish"] += 1
        elif "NEUTRAL" in trend or "RANGE" in trend or "CHOP" in trend:
            votes["neutral"] += 1
    return votes


def detect_market_regime(market: dict[str, Any] | None = None, technical: dict[str, Any] | None = None) -> dict[str, Any]:
    market = market if isinstance(market, dict) else {}
    raw = market.get("raw") if isinstance(market.get("raw"), dict) else {}
    regime = explicit_regime(market, raw)
    evidence: list[str] = []

    if regime:
        return {
            "detector_version": MARKET_REGIME_DETECTOR_VERSION,
            "market_regime": regime,
            "confidence": "EXPLICIT",
            "evidence": ["explicit_regime"],
            "not_order_instruction": True,
        }

    label = safe_upper(market.get("label") or raw.get("label") or raw.get("status"), "")
    event_risk = bool(market.get("event_risk") or raw.get("event_risk") or raw.get("earnings_soon") or raw.get("macro_event_risk"))
    vix = safe_float(market.get("vix") or raw.get("vix"), None)
    atr_pct = safe_float(market.get("atr_pct") or raw.get("atr_pct"), None)
    adx = safe_float(market.get("adx") or raw.get("adx"), None)

    if event_risk:
        evidence.append("event_risk")
    if vix is not None:
        evidence.append(f"vix={vix}")
    if atr_pct is not None:
        evidence.append(f"atr_pct={atr_pct}")
    if adx is not None:
        evidence.append(f"adx={adx}")

    if event_risk or (vix is not None and vix >= 25) or (atr_pct is not None and atr_pct >= 3.0) or "EVENT" in label or "HIGH_VOL" in label:
        return {
            "detector_version": MARKET_REGIME_DETECTOR_VERSION,
            "market_regime": "HIGH_VOL_EVENT_RISK",
            "confidence": "DERIVED",
            "evidence": evidence or ["high_vol_label"],
            "not_order_instruction": True,
        }

    votes = _technical_votes(technical or {})
    if votes["intraday"] > 0 and adx is not None and adx >= 20:
        return {
            "detector_version": MARKET_REGIME_DETECTOR_VERSION,
            "market_regime": "INTRADAY_TREND",
            "confidence": "DERIVED",
            "evidence": evidence + [f"intraday_votes={votes['intraday']}", f"adx={adx}"],
            "not_order_instruction": True,
        }
    if votes["bearish"] > max(votes["bullish"], votes["neutral"]):
        return {
            "detector_version": MARKET_REGIME_DETECTOR_VERSION,
            "market_regime": "BEARISH_OR_CORRECTION",
            "confidence": "DERIVED",
            "evidence": evidence + [f"bearish_votes={votes['bearish']}"],
            "not_order_instruction": True,
        }
    if votes["bullish"] > 0 and votes["bearish"] == 0 and (vix is None or vix < 20):
        return {
            "detector_version": MARKET_REGIME_DETECTOR_VERSION,
            "market_regime": "BULLISH_LOW_VOL",
            "confidence": "DERIVED",
            "evidence": evidence + [f"bullish_votes={votes['bullish']}"],
            "not_order_instruction": True,
        }
    if votes["neutral"] > 0 or "RANGE" in label or "NEUTRAL" in label:
        return {
            "detector_version": MARKET_REGIME_DETECTOR_VERSION,
            "market_regime": "NEUTRAL_RANGE",
            "confidence": "DERIVED",
            "evidence": evidence + [f"neutral_votes={votes['neutral']}"],
            "not_order_instruction": True,
        }

    return {
        "detector_version": MARKET_REGIME_DETECTOR_VERSION,
        "market_regime": "UNKNOWN",
        "confidence": "INSUFFICIENT_DATA",
        "evidence": evidence,
        "not_order_instruction": True,
    }
