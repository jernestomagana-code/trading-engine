from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime, timezone
import json, re, os, math, requests

app = FastAPI(title="Super Engine Bolsa", version="4.0.0")
SIGNALS_FILE = "signals_history.json"
SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
EXPIRATION_MINUTES = {"5m": 25, "15m": 90, "1h": 360, "1d": 1440}
trade_store: Dict[str, Dict[str, Dict[str, Any]]] = {}

class TradingSignal(BaseModel):
    ticker: Optional[str] = "UNKNOWN"
    timeframe: Optional[str] = "unknown"
    setup: Optional[str] = "WAIT"
    trend: Optional[str] = ""
    score: Optional[float] = 0
    price: Optional[float] = None
    entry: Optional[float] = None
    stop: Optional[float] = None
    target: Optional[float] = None
    volume_relative: Optional[float] = None
    rsi: Optional[float] = None
    macd_state: Optional[str] = None
    adx: Optional[float] = None
    vwap_position: Optional[str] = None
    iv_rank: Optional[float] = None
    state: Optional[str] = None
    grade: Optional[str] = None
    conviction: Optional[str] = None
    priority_score: Optional[float] = None
    extra: Optional[Dict[str, Any]] = None

class PositionSizingRequest(BaseModel):
    account_size: float
    risk_percent: float = 1.0
    entry: float
    stop: float

class OptionEvalRequest(BaseModel):
    ticker: str
    strategy: str = "NAKED_PUT"
    strike: Optional[float] = None
    premium: Optional[float] = None
    dte: Optional[int] = None
    account_size: Optional[float] = None
    margin_required: Optional[float] = None
    iv_rank: Optional[float] = None

def now_utc(): return datetime.now(timezone.utc)

def safe_float(v, default=0.0):
    try:
        if v is None: return default
        return float(v)
    except Exception:
        return default

def supabase_enabled(): return bool(SUPABASE_URL and SUPABASE_KEY)

def supabase_headers(prefer="return=minimal"):
    h = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json"}
    if prefer is not None: h["Prefer"] = prefer
    return h

def supabase_insert_signal(signal):
    if not supabase_enabled():
        return {"enabled": False, "saved": False, "error": "Supabase env vars missing"}
    url = f"{SUPABASE_URL}/rest/v1/trading_signals"
    payload = {
        "ticker": signal.get("ticker", "UNKNOWN"),
        "timeframe": signal.get("timeframe", "unknown"),
        "setup": signal.get("setup"),
        "trend": signal.get("trend"),
        "score": safe_float(signal.get("score", signal.get("technical_score", 0)), None),
        "price": safe_float(signal.get("price", signal.get("close", 0)), None),
        "state": signal.get("state"),
        "grade": signal.get("grade"),
        "conviction": signal.get("conviction"),
        "priority_score": safe_float(signal.get("priority_score", 0), None),
        "received_at": signal.get("received_at"),
        "payload": signal,
    }
    try:
        r = requests.post(url, headers=supabase_headers(), json=payload, timeout=10)
        if r.status_code in [200, 201, 204]:
            return {"enabled": True, "saved": True, "status_code": r.status_code}
        return {"enabled": True, "saved": False, "status_code": r.status_code, "error": r.text[:800]}
    except Exception as e:
        return {"enabled": True, "saved": False, "error": str(e)}

def supabase_fetch_signals(limit=3000):
    if not supabase_enabled(): return []
    url = f"{SUPABASE_URL}/rest/v1/trading_signals?select=payload&order=received_at.desc&limit={limit}"
    try:
        r = requests.get(url, headers=supabase_headers(None), timeout=10)
        if r.status_code != 200: return []
        out = []
        for row in r.json():
            p = row.get("payload")
            if isinstance(p, dict): out.append(p)
        return list(reversed(out))
    except Exception:
        return []

def supabase_count_signals():
    if not supabase_enabled(): return {"enabled": False, "count": 0}
    try:
        h = supabase_headers(None); h["Prefer"] = "count=exact"
        r = requests.get(f"{SUPABASE_URL}/rest/v1/trading_signals?select=id", headers=h, timeout=10)
        return {"enabled": True, "status_code": r.status_code, "content_range": r.headers.get("content-range",""), "ok": r.status_code in [200,206]}
    except Exception as e:
        return {"enabled": True, "ok": False, "error": str(e)}

def load_signals_from_file():
    if os.path.exists(SIGNALS_FILE):
        try:
            with open(SIGNALS_FILE, "r") as f: return json.load(f)
        except Exception: return []
    return []

def load_signals(limit=3000):
    s = supabase_fetch_signals(limit)
    return s if s else load_signals_from_file()[-limit:]

def save_signal_file(signal):
    s = load_signals_from_file(); s.append(signal); s = s[-10000:]
    with open(SIGNALS_FILE, "w") as f: json.dump(s, f, indent=2)

def save_signal(signal):
    save_signal_file(signal)
    return supabase_insert_signal(signal)

def extract_json_from_text(text: str):
    try: return json.loads(text)
    except Exception: pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try: return json.loads(text[start:end+1])
        except Exception: pass
    return None

def normalize_timeframe(tf):
    tf = str(tf).lower().replace("min","").replace("m","").strip()
    if tf == "5": return "5m"
    if tf == "15": return "15m"
    if tf in ["60","1h","h"]: return "1h"
    if tf in ["d","1d","day"]: return "1d"
    return tf or "unknown"

def find_ticker(data, raw_text):
    if isinstance(data, dict):
        ticker = data.get("ticker") or data.get("symbol") or data.get("tickerid")
        if ticker: return str(ticker).upper().strip()
    m = re.search(r'"ticker"\s*:\s*"([^"]+)"', raw_text)
    if m: return m.group(1).upper().strip()
    m = re.search(r'\b(SPY|QQQ|TLT|MSFT|GOOG|AMZN|AAPL|NVDA|META|TSLA|NFLX|USTEC\.F|MNQ|NQ|ES|SPX|IWM|VIX|DXY)\b', raw_text)
    return m.group(1).upper().strip() if m else "UNKNOWN"

def signal_age_minutes(signal):
    ts = signal.get("received_at")
    if not ts: return None
    try:
        return round((now_utc() - datetime.fromisoformat(ts)).total_seconds()/60, 2)
    except Exception:
        return None

def is_expired(signal, timeframe):
    age = signal_age_minutes(signal)
    return True if age is None else age > EXPIRATION_MINUTES.get(timeframe, 60)

def freshness_score(signal, timeframe):
    age = signal_age_minutes(signal)
    if age is None: return 0
    limit = EXPIRATION_MINUTES.get(timeframe, 60)
    if age <= limit * .25: return 100
    if age <= limit * .50: return 75
    if age <= limit: return 50
    return 0

def enrich_signal(signal, timeframe):
    x = dict(signal)
    x["age_minutes"] = signal_age_minutes(x)
    x["expires_after_minutes"] = EXPIRATION_MINUTES.get(timeframe, 60)
    x["expired"] = is_expired(x, timeframe)
    x["freshness_score"] = freshness_score(x, timeframe)
    return x

def active_timeframes(timeframes):
    active = {}
    for tf, sig in timeframes.items():
        e = enrich_signal(sig, tf)
        if not e["expired"]: active[tf] = e
    return active

def get_trend(signal): return str(signal.get("trend", "")).lower()
def get_setup(signal): return str(signal.get("setup", "WAIT")).upper()
def get_score(signal): return safe_float(signal.get("score", signal.get("technical_score", 0)), 0)

def rebuild_store_from_history():
    store = {}
    for sig in load_signals(3000):
        ticker = str(sig.get("ticker","UNKNOWN")).upper().strip()
        tf = normalize_timeframe(sig.get("timeframe","unknown"))
        store.setdefault(ticker, {})[tf] = sig
    return store

def calculate_alignment_score(has_1h, has_15, has_5, bullish_1h, bullish_15, bullish_5, bearish_1h, bearish_15, bearish_5):
    if has_1h and has_15 and has_5:
        if bullish_1h and bullish_15 and bullish_5: return 100, "bullish_full"
        if bearish_1h and bearish_15 and bearish_5: return 100, "bearish_full"
        if (bullish_1h and bullish_15) or (bearish_1h and bearish_15): return 75, "higher_tf_aligned_no_trigger"
        if (bullish_1h and bullish_5) or (bearish_1h and bearish_5): return 60, "partial_alignment"
        return 35, "mixed"
    if has_1h and has_15:
        if bullish_1h and bullish_15: return 80, "bullish_context_setup"
        if bearish_1h and bearish_15: return 80, "bearish_context_setup"
        return 45, "mixed_1h_15m"
    if has_1h:
        if bullish_1h: return 60, "bullish_context_only"
        if bearish_1h: return 60, "bearish_context_only"
    return 20, "insufficient_alignment"

def calculate_priority_score(state, grade, conviction, weighted_score, freshness_weighted, alignment, regime="MIXED_OR_CHOP"):
    score = weighted_score
    score += {"A+":10, "A":6, "B":2}.get(grade, 0)
    score += {"VERY_HIGH":10, "HIGH":6, "MEDIUM":2}.get(conviction, 0)
    if state in ["LONG_READY","SHORT_READY"]: score += 8
    elif state in ["LONG_ACTIVE","SHORT_ACTIVE"]: score += 6
    elif state in ["PRE_LONG","PRE_SHORT"]: score += 3
    elif state in ["EXTENDED_LONG","EXTENDED_SHORT"]: score -= 12
    elif state in ["WAIT","MIXED","NO_DATA","CHOP"]: score -= 15
    if alignment in ["bullish","bearish"]: score += 5
    elif "partial" in alignment: score -= 3
    if freshness_weighted < 50: score -= 10
    if regime in ["STRONG_BULL","BULL"] and "LONG" in state: score += 4
    if regime in ["BEAR","PANIC"] and "SHORT" in state: score += 4
    if regime in ["CHOP","RANGE"] and state in ["LONG_READY","SHORT_READY","LONG_ACTIVE","SHORT_ACTIVE"]: score -= 8
    return round(max(0, min(score, 100)), 2)

def probability_engine(classification, regime="MIXED_OR_CHOP"):
    state = classification.get("state","NO_DATA")
    priority = safe_float(classification.get("priority_score"), 0)
    alignment_score = safe_float(classification.get("alignment_score"), 20)
    freshness = safe_float(classification.get("freshness_weighted"), 0)
    base = 45 + (priority-50)*.28 + (alignment_score-50)*.18 + (freshness-50)*.10
    if state in ["LONG_READY","SHORT_READY"]: base += 8
    elif state in ["LONG_ACTIVE","SHORT_ACTIVE"]: base += 6
    elif state in ["PRE_LONG","PRE_SHORT"]: base += 2
    elif state in ["EXTENDED_LONG","EXTENDED_SHORT"]: base -= 10
    elif state in ["WAIT","NO_DATA","MIXED","CHOP"]: base -= 12
    if regime in ["STRONG_BULL","BULL","BEAR"]: base += 3
    elif regime in ["CHOP","RANGE"]: base -= 5
    elif regime == "PANIC": base -= 4
    p = round(max(5, min(base, 92)), 1)
    confidence = "HIGH" if p >= 80 else "MEDIUM_HIGH" if p >= 68 else "MEDIUM" if p >= 56 else "LOW"
    risk = "LOW" if p >= 78 and state not in ["EXTENDED_LONG","EXTENDED_SHORT"] else "MEDIUM" if p >= 60 else "HIGH"
    return {"probability_estimate": p, "confidence": confidence, "risk": risk, "note": "Heurístico interno; aún no usa IV/flow/gamma reales."}

def expected_pl_engine(classification, account_size=None):
    priority = safe_float(classification.get("priority_score"), 0)
    entry, stop = safe_float(classification.get("entry"), 0), safe_float(classification.get("stop"), 0)
    risk_budget = (account_size * .01) if account_size else 1000
    units = math.floor(risk_budget / abs(entry-stop)) if entry and stop and abs(entry-stop) > 0 else None
    base = round((priority - 50) * 12, 2)
    return {"base_case_pl": base, "favorable_case_pl": round(base*2,2), "adverse_case_pl": round(-risk_budget,2), "risk_budget_assumption": risk_budget, "suggested_units_if_entry_stop_available": units, "note": "Placeholder operativo."}

def risk_engine(classification, regime="MIXED_OR_CHOP"):
    state = classification.get("state","NO_DATA")
    missing = classification.get("missing_timeframes", [])
    priority = safe_float(classification.get("priority_score"), 0)
    warnings, allowed = [], True
    if state in ["NO_DATA","WAIT","MIXED","CHOP"]:
        warnings.append("No hay edge suficiente."); allowed = False
    if state in ["EXTENDED_LONG","EXTENDED_SHORT"]:
        warnings.append("Movimiento extendido: no perseguir."); allowed = False
    if "5m" in missing and state not in ["PRE_LONG","PRE_SHORT"]: warnings.append("Falta gatillo 5m.")
    if regime in ["CHOP","RANGE"] and priority < 85:
        warnings.append("Régimen de mercado reduce edge."); allowed = False
    if priority < 65:
        warnings.append("Priority score insuficiente."); allowed = False
    return {"trade_allowed": allowed, "risk_level": "LOW" if allowed and priority >= 85 else "MEDIUM" if priority >= 70 else "HIGH", "warnings": warnings, "capital_preservation_bias": not allowed}

def classify_asset(timeframes, regime="MIXED_OR_CHOP"):
    active = active_timeframes(timeframes)
    tf_5, tf_15, tf_1h, tf_1d = active.get("5m",{}), active.get("15m",{}), active.get("1h",{}), active.get("1d",{})
    setup_5, setup_15 = get_setup(tf_5), get_setup(tf_15)
    trend_15, trend_1h = get_trend(tf_15), get_trend(tf_1h)
    score_5, score_15, score_1h, score_1d = get_score(tf_5), get_score(tf_15), get_score(tf_1h), get_score(tf_1d)
    fresh_5, fresh_15, fresh_1h, fresh_1d = safe_float(tf_5.get("freshness_score"),0), safe_float(tf_15.get("freshness_score"),0), safe_float(tf_1h.get("freshness_score"),0), safe_float(tf_1d.get("freshness_score"),0)
    technical_score = score_5*.30 + score_15*.30 + score_1h*.30 + score_1d*.10
    freshness_weighted = fresh_5*.30 + fresh_15*.30 + fresh_1h*.30 + fresh_1d*.10
    weighted_score = round(technical_score*.80 + freshness_weighted*.20, 2)
    bullish_5, bearish_5 = ("LONG" in setup_5 or "SELL PUT" in setup_5), ("SHORT" in setup_5 or "SELL CALL" in setup_5)
    bullish_15, bearish_15 = (trend_15 == "bullish" or "LONG" in setup_15 or "SELL PUT" in setup_15), (trend_15 == "bearish" or "SHORT" in setup_15 or "SELL CALL" in setup_15)
    bullish_1h, bearish_1h = trend_1h == "bullish", trend_1h == "bearish"
    has_5, has_15, has_1h = bool(tf_5), bool(tf_15), bool(tf_1h)
    alignment_score, alignment_detail = calculate_alignment_score(has_1h, has_15, has_5, bullish_1h, bullish_15, bullish_5, bearish_1h, bearish_15, bearish_5)
    state, action, grade, conviction, strategy_type, alignment = "NO_DATA", "WAIT", "C", "LOW", "none", "mixed"
    recommendation, reason = "Esperar.", "No hay señales frescas suficientes."
    if has_1h and not has_15 and not has_5:
        if bullish_1h:
            state, strategy_type, alignment, reason, recommendation = "PRE_LONG","swing_theta_radar","bullish_context","1h bullish fresco, falta confirmación 15m y gatillo 5m.","Radar alcista temprano. No ejecutar todavía."
        elif bearish_1h:
            state, strategy_type, alignment, reason, recommendation = "PRE_SHORT","short_or_covered_call_radar","bearish_context","1h bearish fresco, falta confirmación 15m y gatillo 5m.","Radar bajista temprano. No ejecutar todavía."
        else:
            state, reason = "MIXED","1h fresco pero sin dirección clara."
    elif has_1h and has_15 and not has_5:
        if bullish_1h and bullish_15:
            state, strategy_type, alignment, reason, recommendation = "PRE_LONG","swing_theta_radar","bullish","1h y 15m bullish. Falta gatillo fresco de 5m.","Preparar swing long o naked put; esperar gatillo 5m."
        elif bearish_1h and bearish_15:
            state, strategy_type, alignment, reason, recommendation = "PRE_SHORT","short_or_covered_call_radar","bearish","1h y 15m bearish. Falta gatillo fresco de 5m.","Preparar short táctico o covered call; esperar gatillo 5m."
        else:
            state, reason = "MIXED","1h y 15m no están alineados."
    elif has_1h and has_15 and has_5:
        if bullish_1h and bullish_15 and bullish_5:
            action, alignment, strategy_type = setup_5, "bullish", "swing_long_theta_or_intraday_a"
            if score_5 >= 90 and fresh_5 >= 75: state, reason = "LONG_ACTIVE","Momentum alcista activo con 1h, 15m y 5m alineados."
            elif score_5 >= 80: state, reason = "LONG_READY","Confluencia alcista multi-timeframe con gatillo 5m."
            else: state, reason = "PARTIAL_LONG","Alineación alcista, pero el gatillo 5m no tiene suficiente fuerza."
            recommendation = "Evaluar swing long, intradía A/A+ o timing para naked put; validar riesgo e invalidación."
        elif bearish_1h and bearish_15 and bearish_5:
            action, alignment, strategy_type = setup_5, "bearish", "short_tactical_or_sell_call"
            if score_5 >= 90 and fresh_5 >= 75: state, reason = "SHORT_ACTIVE","Momentum bajista activo con 1h, 15m y 5m alineados."
            elif score_5 >= 80: state, reason = "SHORT_READY","Confluencia bajista multi-timeframe con gatillo 5m."
            else: state, reason = "PARTIAL_SHORT","Alineación bajista, pero el gatillo 5m no tiene suficiente fuerza."
            recommendation = "Evaluar short táctico o covered call/sell call; validar riesgo e invalidación."
        elif bullish_1h and bullish_5 and not bullish_15:
            state, action, alignment, strategy_type, reason, recommendation = "PARTIAL_LONG", setup_5, "partial_bullish", "partial_radar", "1h y 5m alcistas, pero falta confirmación 15m.", "No ejecutar agresivo; esperar confirmación 15m."
        elif bearish_1h and bearish_5 and not bearish_15:
            state, action, alignment, strategy_type, reason, recommendation = "PARTIAL_SHORT", setup_5, "partial_bearish", "partial_radar", "1h y 5m bajistas, pero falta confirmación 15m.", "No ejecutar agresivo; esperar confirmación 15m."
        else:
            state, reason = "WAIT", "Hay señales frescas, pero no existe confluencia operable."
    if state in ["LONG_ACTIVE","SHORT_ACTIVE"]: conviction = "VERY_HIGH" if weighted_score >= 88 else "HIGH"
    elif state in ["LONG_READY","SHORT_READY"]: conviction = "HIGH" if weighted_score >= 80 else "MEDIUM"
    elif state in ["PRE_LONG","PRE_SHORT","PARTIAL_LONG","PARTIAL_SHORT"]: conviction = "MEDIUM" if weighted_score >= 70 else "LOW"
    if action != "WAIT":
        grade = "A+" if weighted_score >= 88 and conviction in ["VERY_HIGH","HIGH"] else "A" if weighted_score >= 80 else "B" if weighted_score >= 70 else "C"
    elif state in ["PRE_LONG","PRE_SHORT"] and weighted_score >= 70:
        grade = "B"
    if state == "LONG_ACTIVE" and score_5 >= 95:
        state, recommendation, reason = "EXTENDED_LONG", "No perseguir. Esperar pullback o nueva base.", "Momentum alcista fuerte pero potencialmente extendido."
    if state == "SHORT_ACTIVE" and score_5 >= 95:
        state, recommendation, reason = "EXTENDED_SHORT", "No perseguir. Esperar rebote o nueva base.", "Momentum bajista fuerte pero potencialmente extendido."
    entry = tf_5.get("entry") or tf_5.get("price") or tf_15.get("price") or tf_1h.get("price")
    stop, target = tf_5.get("stop"), tf_5.get("target")
    missing = []
    if not has_1h: missing.append("1h")
    if not has_15: missing.append("15m")
    if not has_5: missing.append("5m")
    priority_score = calculate_priority_score(state, grade, conviction, weighted_score, freshness_weighted, alignment, regime)
    output = {"state": state, "grade": grade, "conviction": conviction, "action": action, "strategy_type": strategy_type, "alignment": alignment, "alignment_score": alignment_score, "alignment_detail": alignment_detail, "weighted_score": weighted_score, "technical_score": round(technical_score,2), "freshness_weighted": round(freshness_weighted,2), "priority_score": priority_score, "recommendation": recommendation, "reason": reason, "entry": entry, "stop": stop, "target": target, "missing_timeframes": missing, "active_timeframes": active, "all_timeframes": timeframes}
    output["probability"] = probability_engine(output, regime)
    output["risk"] = risk_engine(output, regime)
    output["expected_pl"] = expected_pl_engine(output)
    return output

def market_regime():
    spy = classify_asset(trade_store.get("SPY", {}), "MIXED_OR_CHOP") if "SPY" in trade_store else None
    qqq = classify_asset(trade_store.get("QQQ", {}), "MIXED_OR_CHOP") if "QQQ" in trade_store else None
    tlt = classify_asset(trade_store.get("TLT", {}), "MIXED_OR_CHOP") if "TLT" in trade_store else None
    iwm = classify_asset(trade_store.get("IWM", {}), "MIXED_OR_CHOP") if "IWM" in trade_store else None
    vix = classify_asset(trade_store.get("VIX", {}), "MIXED_OR_CHOP") if "VIX" in trade_store else None
    bullish = bearish = partial = 0
    for item in [spy, qqq, iwm]:
        if item:
            if item["alignment"] in ["bullish","bullish_context","partial_bullish"]: bullish += 1
            if item["alignment"] in ["bearish","bearish_context","partial_bearish"]: bearish += 1
            if "partial" in item["alignment"]: partial += 1
    if bullish >= 2 and bearish == 0:
        regime, summary = ("STRONG_BULL" if qqq and qqq.get("priority_score",0) >= 75 else "BULL"), "Índices principales muestran sesgo alcista."
    elif bearish >= 2 and bullish == 0:
        regime, summary = "BEAR", "Índices principales muestran sesgo bajista."
    elif bullish >= 1 and bearish >= 1:
        regime, summary = "CHOP", "Lectura mixta entre índices; riesgo de falsas rupturas."
    elif partial >= 2:
        regime, summary = "RANGE", "Señales parciales; mercado en posible rango."
    else:
        regime, summary = "MIXED_OR_CHOP", "No hay alineación clara entre índices principales."
    return {"regime": regime, "summary": summary, "spy": spy, "qqq": qqq, "tlt": tlt, "iwm": iwm, "vix": vix}

def strategy_selection(classification, regime="MIXED_OR_CHOP"):
    state, grade = classification["state"], classification["grade"]
    prob = classification.get("probability", {}).get("probability_estimate", 0)
    if state in ["LONG_READY","LONG_ACTIVE"] and grade in ["A+","A"] and regime in ["STRONG_BULL","BULL","MIXED_OR_CHOP"]:
        return {"primary_strategy":"Swing Long / Tactical Long","secondary_strategy":"Naked Put if IV is attractive","avoid":"No perseguir si está extendido","strategy_score":prob}
    if state in ["PRE_LONG","PARTIAL_LONG"]:
        return {"primary_strategy":"Radar Swing Long","secondary_strategy":"Preparar Naked Put si confirma 5m/15m","avoid":"Entrada anticipada sin gatillo fresco","strategy_score":prob}
    if state in ["SHORT_READY","SHORT_ACTIVE"] and grade in ["A+","A"]:
        return {"primary_strategy":"Tactical Short","secondary_strategy":"Covered Call / Sell Call if holding shares","avoid":"Short si está sobreextendido","strategy_score":prob}
    if state in ["PRE_SHORT","PARTIAL_SHORT"]:
        return {"primary_strategy":"Radar Bearish","secondary_strategy":"Covered Call si existe posición","avoid":"Short agresivo sin confirmación","strategy_score":prob}
    if state == "EXTENDED_LONG":
        return {"primary_strategy":"Defense / Wait","secondary_strategy":"Covered Call candidate if holding shares and IV attractive","avoid":"Perseguir movimiento","strategy_score":prob}
    if state == "EXTENDED_SHORT":
        return {"primary_strategy":"Defense / Wait","secondary_strategy":"Wait for bounce/base before short continuation","avoid":"Perseguir movimiento","strategy_score":prob}
    return {"primary_strategy":"Wait / No Trade","secondary_strategy":"Capital preservation","avoid":"Forzar operación sin edge","strategy_score":prob}

def theta_engine(classification, regime="MIXED_OR_CHOP"):
    state, priority = classification.get("state"), classification.get("priority_score", 0)
    if state in ["PRE_LONG","LONG_READY","LONG_ACTIVE","PARTIAL_LONG"] and regime in ["STRONG_BULL","BULL","MIXED_OR_CHOP"]:
        return {"naked_put_bias":"FAVORABLE" if priority >= 70 else "WATCH","covered_call_bias":"LOW","preferred_condition":"Vender put solo si soporte es claro, IV es suficiente y no hay evento binario cercano."}
    if state == "EXTENDED_LONG":
        return {"naked_put_bias":"WAIT","covered_call_bias":"FAVORABLE_IF_HOLDING_SHARES","preferred_condition":"Covered call solo si hay posición y resistencia clara."}
    if state in ["PRE_SHORT","SHORT_READY","SHORT_ACTIVE","PARTIAL_SHORT"]:
        return {"naked_put_bias":"AVOID","covered_call_bias":"FAVORABLE_IF_HOLDING_SHARES","preferred_condition":"Priorizar defensa; no vender puts en deterioro técnico."}
    return {"naked_put_bias":"NEUTRAL","covered_call_bias":"NEUTRAL","preferred_condition":"No theta trade sin edge técnico/volatilidad."}

def build_dashboard():
    regime = market_regime()["regime"]
    dash = []
    for ticker, tf in trade_store.items():
        c = classify_asset(tf, regime)
        strategy, theta = strategy_selection(c, regime), theta_engine(c, regime)
        dash.append({"ticker":ticker, "state":c["state"], "grade":c["grade"], "conviction":c["conviction"], "action":c["action"], "strategy_type":c["strategy_type"], "primary_strategy":strategy["primary_strategy"], "secondary_strategy":strategy["secondary_strategy"], "strategy_score":strategy["strategy_score"], "theta":theta, "avoid":strategy["avoid"], "alignment":c["alignment"], "alignment_score":c["alignment_score"], "weighted_score":c["weighted_score"], "priority_score":c["priority_score"], "probability":c["probability"], "risk":c["risk"], "expected_pl":c["expected_pl"], "freshness_weighted":c["freshness_weighted"], "recommendation":c["recommendation"], "reason":c["reason"], "missing_timeframes":c["missing_timeframes"]})
    return sorted(dash, key=lambda x: (x["priority_score"], x["weighted_score"]), reverse=True)

def stats_from_signals(signals):
    by_ticker, by_timeframe, by_setup, by_state = {}, {}, {}, {}
    for s in signals:
        ticker, tf, setup, state = str(s.get("ticker","UNKNOWN")).upper(), str(s.get("timeframe","unknown")), str(s.get("setup","WAIT")), str(s.get("state","NO_DATA"))
        by_ticker[ticker] = by_ticker.get(ticker,0)+1
        by_timeframe[tf] = by_timeframe.get(tf,0)+1
        by_setup[setup] = by_setup.get(setup,0)+1
        by_state[state] = by_state.get(state,0)+1
    return {"total_signals":len(signals), "by_ticker":by_ticker, "by_timeframe":by_timeframe, "by_setup":by_setup, "by_state":by_state}

def process_signal_payload(parsed, source="tradingview", raw_text=""):
    ticker, timeframe = find_ticker(parsed, raw_text or json.dumps(parsed)), normalize_timeframe(parsed.get("timeframe","unknown"))
    parsed.update({"ticker":ticker, "timeframe":timeframe, "received_at":now_utc().isoformat(), "saved_at":now_utc().isoformat(), "source":source})
    if raw_text: parsed["raw_payload_preview"] = raw_text[:500]
    trade_store.setdefault(ticker, {})[timeframe] = parsed
    regime = market_regime()["regime"]
    c = classify_asset(trade_store[ticker], regime)
    parsed.update({"state":c["state"], "grade":c["grade"], "conviction":c["conviction"], "priority_score":c["priority_score"]})
    trade_store[ticker][timeframe] = parsed
    return ticker, timeframe, c, save_signal(parsed), parsed

@app.on_event("startup")
def startup():
    global trade_store
    trade_store = rebuild_store_from_history()

@app.get("/")
def root(): return {"status":"alive", "engine":"Super Engine Bolsa v4.0", "mode":"Decision Intelligence Core"}

@app.get("/health")
def health():
    signals = load_signals(limit=100)
    return {"status":"ok", "engine":"Super Engine Bolsa v4.0", "supabase_enabled":supabase_enabled(), "total_recent_signals_loaded":len(signals), "tickers_in_memory":list(trade_store.keys()), "last_signal":signals[-1] if signals else None, "expiration_minutes":EXPIRATION_MINUTES}

@app.post("/webhook/tradingview")
async def tradingview_webhook(request: Request):
    raw = (await request.body()).decode("utf-8", errors="ignore").strip()
    parsed = extract_json_from_text(raw)
    if not isinstance(parsed, dict): parsed = {"raw_message": raw, "parse_warning": "payload not valid json"}
    ticker, timeframe, c, storage, parsed = process_signal_payload(parsed, "tradingview", raw)
    return {"status":"ok", "engine":"v4.0", "message":f"Webhook received for {ticker} {timeframe}", "ticker":ticker, "timeframe":timeframe, "storage":storage, "classification":c, "data":parsed}

@app.post("/test_signal")
def test_signal(signal: TradingSignal):
    parsed = signal.dict(exclude_none=True)
    if parsed.get("extra"): parsed.update(parsed.pop("extra"))
    ticker, timeframe, c, storage, parsed = process_signal_payload(parsed, "manual_test", json.dumps(parsed))
    return {"status":"ok", "engine":"v4.0", "message":f"Test signal saved for {ticker} {timeframe}", "storage":storage, "classification":c, "data":parsed}

@app.get("/get_trade_context")
def get_trade_context(ticker: str):
    ticker = ticker.upper().strip()
    if ticker not in trade_store: return {"ticker":ticker, "status":"missing_data", "message":"No hay datos todavía para este ticker."}
    regime = market_regime()["regime"]
    c = classify_asset(trade_store[ticker], regime)
    c["strategy_selection"], c["theta_engine"] = strategy_selection(c, regime), theta_engine(c, regime)
    return {"ticker":ticker, "engine":"v4.0", "classification":c}

@app.get("/get_dashboard")
def get_dashboard():
    dash = build_dashboard()
    for i, item in enumerate(dash, start=1): item["priority_rank"] = i
    return {"generated_at":now_utc().isoformat(), "engine":"v4.0", "supabase_enabled":supabase_enabled(), "market_regime":market_regime(), "dashboard":dash, "best_setups":dash[:5]}

@app.get("/get_report")
def get_report():
    dash, regime = build_dashboard(), market_regime()
    for i, item in enumerate(dash, start=1): item["priority_rank"] = i
    lines = ["SUPER ENGINE BOLSA v4.0 — DECISION INTELLIGENCE CORE", f"Generado UTC: {now_utc().isoformat()}", "", "RÉGIMEN DE MERCADO", f"- Estado: {regime['regime']}", f"- Lectura: {regime['summary']}", ""]
    if not dash:
        lines.append("No hay señales suficientes todavía.")
        return {"generated_at":now_utc().isoformat(), "engine":"v4.0", "report":"\n".join(lines), "dashboard":[]}
    ready = [x for x in dash if x["state"] in ["LONG_READY","SHORT_READY","LONG_ACTIVE","SHORT_ACTIVE"]]
    extended = [x for x in dash if x["state"] in ["EXTENDED_LONG","EXTENDED_SHORT"]]
    radar = [x for x in dash if x["state"] in ["PRE_LONG","PRE_SHORT","PARTIAL_LONG","PARTIAL_SHORT"]]
    avoid = [x for x in dash if x["state"] in ["WAIT","NO_DATA","MIXED","MIXED_OR_CHOP","CHOP"]]
    lines += ["RESUMEN EJECUTIVO", f"- Setups listos/activos: {len(ready)}", f"- Extendidos/no perseguir: {len(extended)}", f"- Radar: {len(radar)}", f"- Evitar/sin edge: {len(avoid)}", "", "🏆 TOP PRIORITY SETUPS"]
    for x in dash[:5]:
        lines.append(f"{x['priority_rank']}. {x['ticker']} | {x['grade']} | {x['conviction']} | {x['state']} | Priority {x['priority_score']} | Prob {x['probability']['probability_estimate']}% | Risk {x['risk']['risk_level']} | {x['primary_strategy']}")
    return {"generated_at":now_utc().isoformat(), "engine":"v4.0", "supabase_enabled":supabase_enabled(), "report":"\n".join(lines), "dashboard":dash, "best_setups":dash[:5]}

@app.get("/gpt_report")
def gpt_report():
    dash, regime = build_dashboard(), market_regime()
    best = dash[0] if dash else None
    if not best: return {"engine":"v4.0", "market":regime["regime"], "status":"NO_DATA", "best_setup":None, "plan":"Esperar nuevas señales frescas."}
    return {"engine":"v4.0", "market":regime["regime"], "best_setup":f"{best['ticker']} {best['state']}", "strategy":best["primary_strategy"], "probability":best["probability"]["probability_estimate"], "confidence":best["probability"]["confidence"], "risk":best["risk"]["risk_level"], "trade_allowed":best["risk"]["trade_allowed"], "plan":best["recommendation"], "avoid":best["avoid"], "top_5":dash[:5]}

@app.post("/position_sizing")
def position_sizing(req: PositionSizingRequest):
    risk_budget, unit_risk = req.account_size*(req.risk_percent/100), abs(req.entry-req.stop)
    if unit_risk <= 0: return {"error":"Entry and stop cannot be equal."}
    return {"engine":"v4.0", "account_size":req.account_size, "risk_percent":req.risk_percent, "risk_budget":round(risk_budget,2), "entry":req.entry, "stop":req.stop, "unit_risk":round(unit_risk,4), "suggested_units":math.floor(risk_budget/unit_risk)}

@app.post("/evaluate_option")
def evaluate_option(req: OptionEvalRequest):
    ticker, regime = req.ticker.upper().strip(), market_regime()["regime"]
    context = classify_asset(trade_store.get(ticker, {}), regime) if ticker in trade_store else None
    margin_yield = round((req.premium/req.margin_required)*100, 2) if req.premium and req.margin_required and req.margin_required > 0 else None
    iv_comment = "IV no proporcionada." if req.iv_rank is None else "IV rank favorable para venta de prima." if req.iv_rank >= 50 else "IV rank moderada; venta de prima condicional." if req.iv_rank >= 30 else "IV rank baja; prima puede no compensar riesgo."
    dictamen = "No recomendable: falta contexto técnico reciente."
    if context:
        theta = theta_engine(context, regime)
        if req.strategy.upper() in ["NAKED_PUT","SELL_PUT"] and theta["naked_put_bias"] in ["FAVORABLE","WATCH"]: dictamen = "Condicional/Favorable: revisar soporte, IV, DTE y assignment risk."
        elif req.strategy.upper() in ["COVERED_CALL","SELL_CALL"] and theta["covered_call_bias"] in ["FAVORABLE_IF_HOLDING_SHARES"]: dictamen = "Condicional/Favorable si ya existe posición y resistencia clara."
        else: dictamen = "Condicional: el contexto no favorece claramente la estrategia."
    return {"engine":"v4.0", "ticker":ticker, "strategy":req.strategy, "strike":req.strike, "premium":req.premium, "dte":req.dte, "margin_required":req.margin_required, "premium_on_margin_percent":margin_yield, "iv_rank":req.iv_rank, "iv_comment":iv_comment, "context_available":context is not None, "technical_context":context, "dictamen":dictamen}

@app.get("/latest")
def latest(): return trade_store

@app.get("/history")
def history(limit: int = 100):
    signals = load_signals(limit=limit)
    return {"engine":"v4.0", "supabase_enabled":supabase_enabled(), "showing":min(limit, len(signals)), "signals":signals[-limit:]}

@app.get("/stats")
def stats(limit: int = 1000): return {"engine":"v4.0", "generated_at":now_utc().isoformat(), "stats":stats_from_signals(load_signals(limit=limit))}

@app.get("/stats/ticker/{ticker}")
def stats_ticker(ticker: str, limit: int = 1000):
    ticker = ticker.upper().strip()
    signals = [s for s in load_signals(limit=limit) if str(s.get("ticker","")).upper() == ticker]
    return {"engine":"v4.0", "ticker":ticker, "generated_at":now_utc().isoformat(), "stats":stats_from_signals(signals), "signals":signals[-50:]}

@app.get("/debug/supabase")
def debug_supabase(): return {"engine":"v4.0", "supabase_enabled":supabase_enabled(), "supabase_url_present":bool(SUPABASE_URL), "supabase_key_present":bool(SUPABASE_KEY), "count_test":supabase_count_signals()}

@app.get("/debug/routes")
def debug_routes(): return {"engine":"v4.0", "routes":["/","/health","/webhook/tradingview","/test_signal","/get_trade_context","/get_dashboard","/get_report","/gpt_report","/position_sizing","/evaluate_option","/latest","/history","/stats","/stats/ticker/{ticker}","/debug/supabase","/debug/routes","/debug/regime","/debug/scoring","/dashboard_html"]}

@app.get("/debug/regime")
def debug_regime(): return {"engine":"v4.0", "market_regime":market_regime()}

@app.get("/debug/scoring")
def debug_scoring(ticker: str = "QQQ"):
    ticker = ticker.upper().strip()
    if ticker not in trade_store: return {"engine":"v4.0", "ticker":ticker, "error":"Ticker not in memory"}
    regime = market_regime()["regime"]
    return {"engine":"v4.0", "ticker":ticker, "classification":classify_asset(trade_store[ticker], regime)}

@app.get("/dashboard_html", response_class=HTMLResponse)
def dashboard_html():
    dash, regime = build_dashboard(), market_regime()
    color_map = {"A+":"#0B6E4F", "A":"#1A936F", "B":"#F4A261", "C":"#E76F51"}
    rows = ""
    for i, item in enumerate(dash, start=1):
        color = color_map.get(item["grade"], "#999")
        rows += f"""<tr><td>{i}</td><td>{item['ticker']}</td><td style="background:{color}; color:white; font-weight:bold;">{item['grade']}</td><td>{item['conviction']}</td><td>{item['state']}</td><td>{item['primary_strategy']}</td><td>{item['probability']['probability_estimate']}%</td><td>{item['risk']['risk_level']}</td><td>{item['priority_score']}</td><td>{item['weighted_score']}</td><td>{item['alignment']}</td><td>{item['reason']}</td></tr>"""
    html = f"""<html><head><title>Super Engine Bolsa Dashboard</title><style>body{{font-family:Arial;margin:30px;background:#f7f7f7}}h1{{color:#111}}table{{border-collapse:collapse;width:100%;background:white}}th,td{{border:1px solid #ddd;padding:10px;text-align:left;font-size:13px}}th{{background:#111;color:white}}.regime{{padding:15px;background:white;margin-bottom:20px;border-left:5px solid #111}}.meta{{font-size:13px;color:#555;margin-bottom:20px}}</style></head><body><h1>Super Engine Bolsa v4.0</h1><div class="meta">Supabase enabled: {supabase_enabled()}</div><div class="regime"><b>Market Regime:</b> {regime['regime']}<br><b>Lectura:</b> {regime['summary']}</div><table><tr><th>Rank</th><th>Ticker</th><th>Grade</th><th>Conviction</th><th>State</th><th>Strategy</th><th>Prob</th><th>Risk</th><th>Priority</th><th>Score</th><th>Alignment</th><th>Reason</th></tr>{rows}</table></body></html>"""
    return html
