"""Local technical confirmation engine for Stock Ultimus.

Converts local OHLCV bars (for example, IBKR historical bars) into the
strategy-context technical snapshot shape consumed by the existing V29/V31
decision engine. It is pure calculation: no broker calls and no order execution.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any


ENGINE_NAME = "LOCAL_TECHNICAL_ENGINE"
ENGINE_VERSION = "local_technical_engine_v1"
SNAPSHOT_CONTRACT_VERSION = "strategy_signal_contract_v1"
MIN_CONFIRMATION_SCORE = 65
MIN_RECOMMENDED_BARS = 30

SUPPORTED_STRATEGIES = [
    "CASH_SECURED_PUT",
    "NAKED_PUT",
    "COVERED_CALL",
    "IRON_CONDOR",
    "INTRADAY_INDEX_FUTURES",
    "FUTURES",
    "CANSLIM_GROWTH_FILTER",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _upper(value: Any, default: str = "UNKNOWN") -> str:
    text = str(value or "").strip().upper()
    return text or default


def _num(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None or (isinstance(value, str) and not value.strip()):
            return default
        number = float(value)
        return default if math.isnan(number) or math.isinf(number) else number
    except Exception:
        return default


def _round(value: float | None, digits: int = 4) -> float | None:
    return None if value is None else round(value, digits)


def normalize_bars(bars: Any) -> list[dict[str, Any]]:
    if not isinstance(bars, list):
        return []
    clean: list[dict[str, Any]] = []
    for raw in bars:
        if not isinstance(raw, dict):
            continue
        close = _num(raw.get("close", raw.get("c", raw.get("last", raw.get("price")))))
        if close is None:
            continue
        clean.append({
            "timestamp": raw.get("timestamp") or raw.get("time") or raw.get("date"),
            "open": _num(raw.get("open", raw.get("o")), close),
            "high": _num(raw.get("high", raw.get("h")), close),
            "low": _num(raw.get("low", raw.get("l")), close),
            "close": close,
            "volume": _num(raw.get("volume", raw.get("v"))),
        })
    return clean


def sma(values: list[float], window: int) -> float | None:
    if window <= 0 or len(values) < window:
        return None
    return sum(values[-window:]) / window


def _previous_sma(values: list[float], window: int) -> float | None:
    if window <= 0 or len(values) <= window:
        return None
    return sum(values[-window - 1 : -1]) / window


def rsi(values: list[float], period: int = 14) -> float | None:
    if len(values) <= period:
        return None
    changes = [values[i] - values[i - 1] for i in range(1, len(values))]
    recent = changes[-period:]
    gains = [max(change, 0.0) for change in recent]
    losses = [abs(min(change, 0.0)) for change in recent]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_gain == 0 and avg_loss == 0:
        return 50.0
    if avg_loss == 0:
        return 100.0
    if avg_gain == 0:
        return 0.0
    return 100 - (100 / (1 + (avg_gain / avg_loss)))


def atr(bars: list[dict[str, Any]], period: int = 14) -> float | None:
    if len(bars) <= period:
        return None
    ranges: list[float] = []
    for index in range(1, len(bars)):
        high = _num(bars[index].get("high"))
        low = _num(bars[index].get("low"))
        previous_close = _num(bars[index - 1].get("close"))
        if high is None or low is None or previous_close is None:
            continue
        ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
    if len(ranges) < period:
        return None
    return sum(ranges[-period:]) / period


def _indicators(bars: list[dict[str, Any]]) -> dict[str, Any]:
    closes = [_num(bar.get("close")) for bar in bars]
    closes = [value for value in closes if value is not None]
    close = closes[-1] if closes else None
    sma_10 = sma(closes, 10)
    sma_20 = sma(closes, 20)
    sma_50 = sma(closes, 50)
    previous_20 = _previous_sma(closes, 20)
    rsi_14 = rsi(closes, 14)
    atr_14 = atr(bars, 14)
    slope = None if sma_20 is None or previous_20 is None else sma_20 - previous_20

    trend = "UNKNOWN"
    if close is not None and sma_20 is not None:
        if sma_50 is not None and close > sma_20 > sma_50 and (slope or 0) > 0:
            trend = "BULLISH"
        elif sma_50 is not None and close < sma_20 < sma_50 and (slope or 0) < 0:
            trend = "BEARISH"
        elif close >= sma_20 and (slope or 0) >= 0:
            trend = "NEUTRAL_TO_BULLISH"
        elif close <= sma_20 and (slope or 0) <= 0:
            trend = "NEUTRAL_TO_BEARISH"
        else:
            trend = "NEUTRAL"

    atr_pct = None if atr_14 is None or not close else (atr_14 / close) * 100
    recent_20 = bars[-20:]
    recent_50 = bars[-50:]

    def range_level(rows: list[dict[str, Any]], field: str, fn: Any) -> float | None:
        values = [_num(row.get(field)) for row in rows]
        clean_values = [value for value in values if value is not None]
        return fn(clean_values) if clean_values else None

    support_20 = range_level(recent_20, "low", min)
    support_50 = range_level(recent_50, "low", min)
    resistance_20 = range_level(recent_20, "high", max)
    resistance_50 = range_level(recent_50, "high", max)
    support_levels = sorted({round(value, 4) for value in [support_20, support_50] if value is not None})
    resistance_levels = sorted({round(value, 4) for value in [resistance_20, resistance_50] if value is not None})
    nearest_support = max([value for value in support_levels if close is None or value <= close], default=support_20)
    nearest_resistance = min([value for value in resistance_levels if close is None or value >= close], default=resistance_20)
    return {
        "close": _round(close),
        "sma_10": _round(sma_10),
        "sma_20": _round(sma_20),
        "sma_50": _round(sma_50),
        "sma_20_slope": _round(slope),
        "rsi_14": _round(rsi_14, 2),
        "atr_14": _round(atr_14),
        "atr_pct": _round(atr_pct, 2),
        "trend": trend,
        "support": _round(nearest_support),
        "support_level": _round(nearest_support),
        "support_levels": support_levels,
        "resistance": _round(nearest_resistance),
        "resistance_level": _round(nearest_resistance),
        "resistance_levels": resistance_levels,
    }


def _result(strategy: str, score: float, trend: str, blockers: list[str], indicators: dict[str, Any]) -> dict[str, Any]:
    score = max(0, min(100, round(score, 2)))
    confirmed = score >= MIN_CONFIRMATION_SCORE and "LOCAL_RSI_UNAVAILABLE" not in blockers
    if not confirmed and "LOCAL_TECHNICAL_NOT_CONFIRMED" not in blockers:
        blockers = [*blockers, "LOCAL_TECHNICAL_NOT_CONFIRMED"]
    return {
        "strategy_context": strategy,
        "score": score,
        "technical_score": score,
        "trend": trend or "UNKNOWN",
        "confirmed": confirmed,
        "blockers": blockers,
        "indicators": indicators,
        "source": ENGINE_NAME,
        "engine_version": ENGINE_VERSION,
        "execution_authorized": False,
        "not_order_instruction": True,
    }


def _cash_secured_put(ind: dict[str, Any]) -> dict[str, Any]:
    score = 0
    blockers: list[str] = []
    trend = ind.get("trend") or "UNKNOWN"
    close = ind.get("close")
    sma_20 = ind.get("sma_20")
    sma_50 = ind.get("sma_50")
    slope = ind.get("sma_20_slope")
    rsi_14 = ind.get("rsi_14")

    if trend in {"BULLISH", "NEUTRAL_TO_BULLISH"}:
        score += 35
    elif trend == "NEUTRAL":
        score += 22
    else:
        blockers.append("LOCAL_TREND_NOT_SUPPORTIVE")
    if close is not None and sma_20 is not None and close >= sma_20:
        score += 20
    else:
        blockers.append("LOCAL_CLOSE_BELOW_FAST_AVERAGE")
    if sma_20 is not None and sma_50 is not None and sma_20 >= sma_50:
        score += 18
    elif sma_50 is None:
        score += 8
        blockers.append("LOCAL_SMA50_UNAVAILABLE")
    else:
        blockers.append("LOCAL_FAST_AVERAGE_BELOW_SLOW_AVERAGE")
    if rsi_14 is not None and 35 <= rsi_14 <= 75:
        score += 17
    elif rsi_14 is None:
        blockers.append("LOCAL_RSI_UNAVAILABLE")
    else:
        blockers.append("LOCAL_RSI_OUTSIDE_PUT_SELLING_RANGE")
    if slope is not None and slope >= 0:
        score += 10
    return _result("CASH_SECURED_PUT", score, trend, blockers, ind)


def _covered_call(ind: dict[str, Any]) -> dict[str, Any]:
    trend = ind.get("trend") or "UNKNOWN"
    rsi_14 = ind.get("rsi_14")
    close = ind.get("close")
    sma_20 = ind.get("sma_20")
    score = 35 if trend in {"NEUTRAL", "NEUTRAL_TO_BEARISH"} else 24
    blockers: list[str] = []
    if rsi_14 is not None and 50 <= rsi_14 <= 82:
        score += 30
    elif rsi_14 is None:
        blockers.append("LOCAL_RSI_UNAVAILABLE")
    else:
        blockers.append("LOCAL_RSI_NOT_IDEAL_FOR_COVERED_CALL")
    score += 20 if close is not None and sma_20 is not None and close >= sma_20 else 8
    score += 15
    return _result("COVERED_CALL", score, trend, blockers, ind)


def _iron_condor(ind: dict[str, Any]) -> dict[str, Any]:
    trend = ind.get("trend") or "UNKNOWN"
    rsi_14 = ind.get("rsi_14")
    atr_pct = ind.get("atr_pct")
    score = 0
    blockers: list[str] = []
    if trend in {"NEUTRAL", "NEUTRAL_TO_BULLISH", "NEUTRAL_TO_BEARISH"}:
        score += 30
    else:
        blockers.append("LOCAL_TREND_NOT_RANGE_BOUND")
    if rsi_14 is not None and 42 <= rsi_14 <= 58:
        score += 35
    elif rsi_14 is None:
        blockers.append("LOCAL_RSI_UNAVAILABLE")
    else:
        blockers.append("LOCAL_RSI_NOT_RANGE_BOUND")
    if atr_pct is not None and atr_pct <= 2.75:
        score += 20
    elif atr_pct is None:
        score += 8
        blockers.append("LOCAL_ATR_UNAVAILABLE")
    else:
        blockers.append("LOCAL_ATR_TOO_HIGH_FOR_RANGE_SETUP")
    score += 15
    return _result("IRON_CONDOR", score, trend, blockers, ind)


def _intraday_futures(ind: dict[str, Any]) -> dict[str, Any]:
    trend = ind.get("trend") or "UNKNOWN"
    close = ind.get("close")
    sma_10 = ind.get("sma_10")
    sma_20 = ind.get("sma_20")
    slope = ind.get("sma_20_slope")
    rsi_14 = ind.get("rsi_14")
    score = 10
    blockers: list[str] = []
    if close is not None and sma_10 is not None and close >= sma_10:
        score += 25
    else:
        blockers.append("LOCAL_PRICE_NOT_ABOVE_INTRADAY_FAST_AVERAGE")
    if sma_10 is not None and sma_20 is not None and sma_10 >= sma_20:
        score += 25
    else:
        blockers.append("LOCAL_INTRADAY_AVERAGE_ALIGNMENT_MISSING")
    if slope is not None and slope >= 0:
        score += 20
    else:
        blockers.append("LOCAL_INTRADAY_MOMENTUM_NOT_CONFIRMED")
    if rsi_14 is not None and 45 <= rsi_14 <= 75:
        score += 20
    elif rsi_14 is None:
        blockers.append("LOCAL_RSI_UNAVAILABLE")
    else:
        blockers.append("LOCAL_RSI_OUTSIDE_INTRADAY_RANGE")
    return _result("INTRADAY_INDEX_FUTURES", score, trend, blockers, ind)


def capabilities() -> dict[str, Any]:
    return {
        "engine": ENGINE_NAME,
        "engine_version": ENGINE_VERSION,
        "snapshot_contract_version": SNAPSHOT_CONTRACT_VERSION,
        "minimum_confirmation_score": MIN_CONFIRMATION_SCORE,
        "minimum_recommended_bars": MIN_RECOMMENDED_BARS,
        "required_bar_fields": ["close"],
        "recommended_bar_fields": ["timestamp", "open", "high", "low", "close", "volume"],
        "supported_strategies": list(SUPPORTED_STRATEGIES),
        "output_shape": "technical_snapshot_by_ticker with by_strategy_context",
        "tradingview_required": False,
        "intended_sources": ["IBKR_HISTORICAL_BARS", "LOCAL_RUNTIME_BARS", "MANUAL_FIXTURE_FOR_TESTING"],
        "execution_authorized": False,
        "not_order_instruction": True,
    }


def evaluate_symbol(ticker: str, bars: Any, strategy: str = "CASH_SECURED_PUT", timeframe: str = "1d") -> dict[str, Any]:
    ticker = _upper(ticker, "")
    strategy = _upper(strategy, "CASH_SECURED_PUT")
    clean = normalize_bars(bars)
    if len(clean) < MIN_RECOMMENDED_BARS:
        contexts = {
            name: _result(name, 0, "UNKNOWN", ["INSUFFICIENT_LOCAL_BARS", "LOCAL_TECHNICAL_NOT_CONFIRMED"], {})
            for name in SUPPORTED_STRATEGIES
        }
        selected = contexts.get(strategy) or contexts["CASH_SECURED_PUT"]
        return {
            "ticker": ticker,
            "source": ENGINE_NAME,
            "engine_layer": ENGINE_NAME,
            "engine_version": ENGINE_VERSION,
            "contract_version": SNAPSHOT_CONTRACT_VERSION,
            "timeframe": timeframe,
            "bars_count": len(clean),
            "score": selected["score"],
            "technical_score": selected["score"],
            "trend": selected["trend"],
            "confirmed": False,
            "blockers": ["INSUFFICIENT_LOCAL_BARS"],
            "available_strategy_contexts": sorted(contexts.keys()),
            "by_strategy_context": contexts,
            "generated_at": _now_iso(),
            "execution_authorized": False,
            "not_order_instruction": True,
        }

    ind = _indicators(clean)
    csp = _cash_secured_put(ind)
    cc = _covered_call(ind)
    ic = _iron_condor(ind)
    fut = _intraday_futures(ind)
    contexts = {
        "CASH_SECURED_PUT": csp,
        "NAKED_PUT": {**csp, "strategy_context": "NAKED_PUT"},
        "COVERED_CALL": cc,
        "IRON_CONDOR": ic,
        "INTRADAY_INDEX_FUTURES": fut,
        "FUTURES": {**fut, "strategy_context": "FUTURES"},
        "CANSLIM_GROWTH_FILTER": {
            **csp,
            "strategy_context": "CANSLIM_GROWTH_FILTER",
            "advisory_note": "Local technical trend only; fundamental CANSLIM data remains a separate input.",
        },
    }
    selected = contexts.get(strategy) or contexts["CASH_SECURED_PUT"]
    return {
        "ticker": ticker,
        "source": ENGINE_NAME,
        "engine_layer": ENGINE_NAME,
        "engine_version": ENGINE_VERSION,
        "contract_version": SNAPSHOT_CONTRACT_VERSION,
        "timeframe": timeframe,
        "bars_count": len(clean),
        "score": selected["score"],
        "technical_score": selected["score"],
        "trend": selected["trend"],
        "confirmed": selected["confirmed"],
        "blockers": selected.get("blockers", []),
        "indicators": ind,
        "price": ind.get("close"),
        "underlying_price": ind.get("close"),
        "support": ind.get("support"),
        "support_level": ind.get("support_level"),
        "support_levels": ind.get("support_levels") or [],
        "resistance": ind.get("resistance"),
        "resistance_level": ind.get("resistance_level"),
        "resistance_levels": ind.get("resistance_levels") or [],
        "strategy_context": selected.get("strategy_context"),
        "available_strategy_contexts": sorted(contexts.keys()),
        "by_strategy_context": contexts,
        "generated_at": _now_iso(),
        "execution_authorized": False,
        "not_order_instruction": True,
    }


def build_technical_snapshot(symbols: Any, strategy: str = "CASH_SECURED_PUT", timeframe: str = "1d") -> dict[str, dict[str, Any]]:
    if isinstance(symbols, dict) and isinstance(symbols.get("symbols"), dict):
        symbols = symbols["symbols"]
    elif isinstance(symbols, dict) and "ticker" in symbols and "bars" in symbols:
        symbols = {symbols.get("ticker"): symbols.get("bars")}
    if not isinstance(symbols, dict):
        return {}
    snapshot: dict[str, dict[str, Any]] = {}
    for ticker, bars in symbols.items():
        normalized_ticker = _upper(ticker, "")
        if normalized_ticker:
            snapshot[normalized_ticker] = evaluate_symbol(normalized_ticker, bars, strategy=strategy, timeframe=timeframe)
    return snapshot
