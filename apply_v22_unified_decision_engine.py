from pathlib import Path

p = Path("app/main.py")
s = p.read_text()

block = r'''
# ============================================================
# V22 — UNIFIED TRADING DECISION ENGINE
# ============================================================

import json as _v22_json
from pathlib import Path as _v22_Path
from datetime import datetime as _v22_datetime, timezone as _v22_timezone

_V22_SAFE_TECH_FILE = _v22_Path("runtime") / "technical_snapshot_by_ticker_safe.json"
_V22_ALT_TECH_FILE = _v22_Path("runtime") / "technical_snapshot_by_ticker.json"
_V22_DECISION_FILE = _v22_Path("runtime") / "decision_desk_snapshot.json"
_V22_ALT_DECISION_FILE = _v22_Path("/tmp") / "decision_desk_snapshot.json"

def _v22_now():
    return _v22_datetime.now(_v22_timezone.utc).isoformat()

def _v22_load_json(path):
    try:
        p = _v22_Path(path)
        if p.exists():
            txt = p.read_text()
            if txt and txt.strip():
                data = _v22_json.loads(txt)
                if isinstance(data, dict):
                    return data
    except Exception:
        pass
    return {}

def _v22_norm_ticker(ticker):
    return str(ticker or "").upper().strip()

def _v22_safe_float(x, default=None):
    try:
        if x is None:
            return default
        return float(x)
    except Exception:
        return default

def _v22_safe_int(x, default=0):
    try:
        if x is None:
            return default
        return int(float(x))
    except Exception:
        return default

def _v22_load_technical_store():
    data = {}

    # 1) Memory safe store
    try:
        mem = globals().get("TECHNICAL_SNAPSHOT_STORE_SAFE", {})
        if isinstance(mem, dict):
            data.update(mem)
    except Exception:
        pass

    # 2) Memory standard store
    try:
        mem = globals().get("TECHNICAL_SNAPSHOT_STORE", {})
        if isinstance(mem, dict):
            data.update(mem)
    except Exception:
        pass

    # 3) Safe runtime file
    try:
        file_data = _v22_load_json(_V22_SAFE_TECH_FILE)
        if isinstance(file_data, dict):
            data.update(file_data)
    except Exception:
        pass

    # 4) Alternate runtime file
    try:
        file_data = _v22_load_json(_V22_ALT_TECH_FILE)
        if isinstance(file_data, dict):
            data.update(file_data)
    except Exception:
        pass

    clean = {}
    for k, v in data.items():
        t = _v22_norm_ticker(k)
        if t and isinstance(v, dict):
            clean[t] = v

    return clean

def _v22_get_market_hours():
    # Try existing V20/V21 helper if present.
    for fn_name in [
        "_v20_market_hours_status",
        "v20_market_hours_status",
        "_get_market_hours_status",
        "get_market_hours_status",
    ]:
        try:
            fn = globals().get(fn_name)
            if callable(fn):
                mh = fn()
                if isinstance(mh, dict):
                    return mh
        except Exception:
            pass

    # Fallback from current system status if available.
    try:
        fn = globals().get("system_status")
        if callable(fn):
            st = fn()
            if isinstance(st, dict):
                mh = st.get("market_hours")
                if isinstance(mh, dict):
                    return mh
    except Exception:
        pass

    return {
        "status": "UNKNOWN",
        "label": "Market hours unknown",
        "is_regular_market_open": False,
        "options_bidask_expected": False,
        "next_check": "Revisar próxima sesión después de 09:35 ET.",
    }

def _v22_load_decision_snapshot():
    data = {}

    # Try existing snapshot helpers.
    for fn_name in [
        "_v18_get_decision_snapshot",
        "get_decision_snapshot",
        "_get_latest_decision_snapshot",
        "_v19_get_operational_dashboard",
    ]:
        try:
            fn = globals().get(fn_name)
            if callable(fn):
                d = fn()
                if isinstance(d, dict):
                    data.update(d)
                    break
        except Exception:
            pass

    # Try runtime files.
    if not data:
        for path in [_V22_DECISION_FILE, _V22_ALT_DECISION_FILE]:
            d = _v22_load_json(path)
            if d:
                data.update(d)
                break

    return data if isinstance(data, dict) else {}

def _v22_extract_rows_from_snapshot(snapshot):
    if not isinstance(snapshot, dict):
        return []

    candidates = []

    for key in ["top", "top_3", "rows", "opportunities", "by_ticker", "by_strategy"]:
        val = snapshot.get(key)
        if isinstance(val, list):
            candidates.extend([x for x in val if isinstance(x, dict)])

    # Sometimes summary contains top_3.
    summary = snapshot.get("summary")
    if isinstance(summary, dict):
        for key in ["top", "top_3", "rows", "opportunities"]:
            val = summary.get(key)
            if isinstance(val, list):
                candidates.extend([x for x in val if isinstance(x, dict)])

    # Best opportunity.
    for key in ["best", "best_opportunity", "next_best_action"]:
        val = snapshot.get(key)
        if isinstance(val, dict):
            candidates.append(val)
    if isinstance(summary, dict):
        for key in ["best", "best_opportunity", "next_best_action"]:
            val = summary.get(key)
            if isinstance(val, dict):
                candidates.append(val)

    # Deduplicate by rough signature.
    out = []
    seen = set()
    for r in candidates:
        t = _v22_norm_ticker(r.get("ticker") or r.get("symbol") or r.get("underlying"))
        strategy = str(r.get("strategy") or r.get("strategy_hint") or r.get("option_type") or "").upper()
        price = str(r.get("price") or r.get("mid") or r.get("premium") or "")
        decision = str(r.get("decision") or r.get("state") or r.get("fusion_state") or "")
        sig = (t, strategy, price, decision)
        if sig not in seen:
            seen.add(sig)
            out.append(r)

    return out

def _v22_get_option_rows_for_ticker(ticker):
    t = _v22_norm_ticker(ticker)
    snapshot = _v22_load_decision_snapshot()
    rows = _v22_extract_rows_from_snapshot(snapshot)
    filtered = []
    for r in rows:
        rt = _v22_norm_ticker(r.get("ticker") or r.get("symbol") or r.get("underlying"))
        if rt == t:
            filtered.append(r)
    return filtered, snapshot

def _v22_best_row(rows):
    if not rows:
        return None

    def score_row(r):
        score = _v22_safe_float(r.get("combined_score"), None)
        if score is None:
            score = _v22_safe_float(r.get("score"), None)
        if score is None:
            score = _v22_safe_float(r.get("technical_score"), 0)
        decision = str(r.get("decision") or r.get("fusion_state") or r.get("state") or "").upper()
        can = bool(r.get("can_operate") is True)
        bonus = 0
        if can:
            bonus += 1000
        if "ENTRY" in decision or decision == "OPERAR":
            bonus += 500
        if "RADAR" in decision:
            bonus += 200
        return bonus + float(score or 0)

    try:
        return sorted(rows, key=score_row, reverse=True)[0]
    except Exception:
        return rows[0]

def _v22_technical_bias_from_snapshot(snapshot):
    if not isinstance(snapshot, dict):
        return "UNKNOWN"

    trend = str(snapshot.get("trend") or snapshot.get("bias") or snapshot.get("technical_bias") or "").upper().strip()
    score = _v22_safe_float(snapshot.get("score") or snapshot.get("technical_score"), None)
    rsi = _v22_safe_float(snapshot.get("rsi"), None)
    vwap = str(snapshot.get("vwap_position") or snapshot.get("vwap") or "").lower()

    if trend in ["BULLISH", "ALCISTA", "UP", "LONG"]:
        return "BULLISH"
    if trend in ["BEARISH", "BAJISTA", "DOWN", "SHORT"]:
        return "BEARISH"
    if trend in ["NEUTRAL", "RANGE", "SIDEWAYS"]:
        return "NEUTRAL"

    if score is not None:
        if score >= 70:
            return "BULLISH"
        if score <= 30:
            return "BEARISH"

    if rsi is not None and vwap:
        if rsi >= 50 and vwap == "above":
            return "BULLISH"
        if rsi <= 45 and vwap == "below":
            return "BEARISH"

    return "UNKNOWN"

def _v22_strategy_from_row(row, technical_bias="UNKNOWN"):
    if isinstance(row, dict):
        for key in ["strategy", "strategy_hint", "best_strategy", "option_strategy"]:
            val = row.get(key)
            if val:
                return str(val).upper().strip()
        opt_type = str(row.get("option_type") or row.get("right") or "").upper()
        if opt_type in ["PUT", "P"]:
            return "NAKED_PUT"
        if opt_type in ["CALL", "C"]:
            return "COVERED_CALL"

    if technical_bias == "BULLISH":
        return "NAKED_PUT"
    if technical_bias == "BEARISH":
        return "COVERED_CALL"
    return "UNKNOWN"

def _v22_is_strategy_aligned(strategy, technical_bias):
    s = str(strategy or "").upper()
    b = str(technical_bias or "").upper()

    if b == "UNKNOWN" or s == "UNKNOWN":
        return None

    if b == "BULLISH" and s in ["NAKED_PUT", "PUT_CREDIT_SPREAD", "BULL_PUT_SPREAD"]:
        return True

    if b == "BEARISH" and s in ["COVERED_CALL", "CALL_CREDIT_SPREAD", "BEAR_CALL_SPREAD"]:
        return True

    if b == "NEUTRAL" and s in ["IRON_CONDOR", "COVERED_CALL", "NAKED_PUT"]:
        return True

    return False

def _v22_main_blocker(market_hours, best_row, technical_snapshot, strategy_alignment):
    mh_status = str((market_hours or {}).get("status") or "").upper()
    options_ok = bool((market_hours or {}).get("options_bidask_expected") is True)

    if mh_status in ["WEEKEND_CLOSED", "HOLIDAY_CLOSED"]:
        return "MARKET_CLOSED"
    if not options_ok:
        return "OPTIONS_MARKET_NOT_RELIABLE"

    if not technical_snapshot:
        return "NO_TECHNICAL_SNAPSHOT"

    if strategy_alignment is False:
        return "TECHNICAL_CONFLICT"

    if not best_row:
        return "WAIT_OPTIONS_DATA"

    missing = best_row.get("missing_confirmations") or best_row.get("missing_data") or []
    if isinstance(missing, str):
        missing = [missing]
    missing_text = " ".join([str(x).upper() for x in missing])

    if "GREEK" in missing_text or "GREEKS" in missing_text:
        return "WAIT_GREEKS"
    if "BID" in missing_text or "ASK" in missing_text or "SPREAD" in missing_text:
        return "WAIT_LIQUIDITY"

    quality = str(best_row.get("data_quality") or best_row.get("quality") or "").upper()
    if "NO_BIDASK" in quality or "PRICE_ONLY" in quality:
        return "WAIT_LIQUIDITY"

    return None

def _v22_final_state(market_hours, best_row, technical_snapshot, technical_bias, strategy, strategy_alignment):
    blocker = _v22_main_blocker(market_hours, best_row, technical_snapshot, strategy_alignment)

    if blocker == "MARKET_CLOSED":
        return "WAIT_MARKET_OPEN"
    if blocker == "OPTIONS_MARKET_NOT_RELIABLE":
        return "WAIT_MARKET_OPEN"
    if blocker == "NO_TECHNICAL_SNAPSHOT":
        return "WAIT_TECHNICAL_DATA"
    if blocker == "TECHNICAL_CONFLICT":
        return "TECHNICAL_CONFLICT"
    if blocker == "WAIT_OPTIONS_DATA":
        return "WAIT_OPTIONS_DATA"
    if blocker == "WAIT_GREEKS":
        return "WAIT_GREEKS"
    if blocker == "WAIT_LIQUIDITY":
        return "WAIT_LIQUIDITY"

    if not best_row and technical_snapshot:
        return "RADAR_TECH_OK"

    can_row = bool(isinstance(best_row, dict) and best_row.get("can_operate") is True)
    decision = str((best_row or {}).get("decision") or (best_row or {}).get("fusion_state") or "").upper()

    if can_row or "ENTRY" in decision or decision == "OPERAR":
        return "ENTRY_READY"

    if technical_snapshot and best_row:
        if strategy_alignment is True:
            return "RADAR_MIXED"
        return "RADAR_OPTIONS_OK"

    if best_row:
        return "RADAR_OPTIONS_OK"

    return "NO_DATA"

def _v22_can_operate(final_state):
    return str(final_state or "").upper() == "ENTRY_READY"

def _v22_action_text(final_state, blocker, market_hours, technical_bias, strategy):
    next_check = (market_hours or {}).get("next_check") or "Revisar próxima ventana operativa."

    if final_state == "ENTRY_READY":
        return "Entrada potencial lista. Validar tamaño, riesgo, spread y confirmación final antes de ejecutar."
    if final_state == "WAIT_MARKET_OPEN":
        return f"No operar ahora. Esperar ventana confiable de mercado/opciones. {next_check}"
    if final_state == "WAIT_LIQUIDITY":
        return "No operar todavía. Confirmar bid/ask y spread real en opciones antes de considerar entrada."
    if final_state == "WAIT_GREEKS":
        return "No operar todavía. Esperar griegas completas para validar delta, IV y riesgo."
    if final_state == "WAIT_OPTIONS_DATA":
        return "No operar todavía. Hay lectura técnica, pero faltan candidatos/opciones completas."
    if final_state == "WAIT_TECHNICAL_DATA":
        return "No operar todavía. Falta snapshot técnico para confirmar dirección y contexto."
    if final_state == "TECHNICAL_CONFLICT":
        return "No operar. La estrategia de opciones no está alineada con el sesgo técnico actual."
    if final_state in ["RADAR_TECH_OK", "RADAR_OPTIONS_OK", "RADAR_MIXED"]:
        return "Mantener en radar. Aún no es entrada operable; esperar confirmaciones completas."
    return "Sin decisión operativa. Revisar datos técnicos, opciones y estado de mercado."

def _v22_severity(final_state):
    if final_state == "ENTRY_READY":
        return "green"
    if final_state in ["RADAR_TECH_OK", "RADAR_OPTIONS_OK", "RADAR_MIXED"]:
        return "amber"
    if final_state in ["WAIT_MARKET_OPEN", "WAIT_LIQUIDITY", "WAIT_GREEKS", "WAIT_OPTIONS_DATA", "WAIT_TECHNICAL_DATA"]:
        return "gray"
    if final_state in ["TECHNICAL_CONFLICT", "BLOCKED"]:
        return "red"
    return "gray"

def _v22_build_trade_decision(ticker):
    t = _v22_norm_ticker(ticker)
    tech_store = _v22_load_technical_store()
    technical_snapshot = tech_store.get(t)
    technical_available = bool(technical_snapshot)

    rows, decision_snapshot = _v22_get_option_rows_for_ticker(t)
    best_row = _v22_best_row(rows)

    market_hours = _v22_get_market_hours()
    technical_bias = _v22_technical_bias_from_snapshot(technical_snapshot)
    technical_score = _v22_safe_float((technical_snapshot or {}).get("score") or (technical_snapshot or {}).get("technical_score"), None)

    strategy = _v22_strategy_from_row(best_row, technical_bias)
    strategy_alignment = _v22_is_strategy_aligned(strategy, technical_bias)

    final_state = _v22_final_state(
        market_hours=market_hours,
        best_row=best_row,
        technical_snapshot=technical_snapshot,
        technical_bias=technical_bias,
        strategy=strategy,
        strategy_alignment=strategy_alignment,
    )

    blocker = _v22_main_blocker(market_hours, best_row, technical_snapshot, strategy_alignment)
    can_operate = _v22_can_operate(final_state)
    action = _v22_action_text(final_state, blocker, market_hours, technical_bias, strategy)

    options_score = None
    if isinstance(best_row, dict):
        options_score = _v22_safe_float(best_row.get("combined_score"), None)
        if options_score is None:
            options_score = _v22_safe_float(best_row.get("score"), None)

    executive_summary = (
        f"{t}: estado {final_state}. "
        f"Sesgo técnico {technical_bias}"
        + (f" con score {technical_score:g}" if technical_score is not None else "")
        + f". Estrategia sugerida/observada: {strategy}. "
        + action
    )

    return {
        "engine": "V22_UNIFIED_TRADING_DECISION_ENGINE",
        "generated_at": _v22_now(),
        "ticker": t,
        "status": "OK",
        "final_state": final_state,
        "decision": final_state,
        "can_operate": can_operate,
        "severity": _v22_severity(final_state),
        "main_blocker": blocker,
        "action": action,
        "executive_summary": executive_summary,

        "technical": {
            "available": technical_available,
            "bias": technical_bias,
            "score": technical_score,
            "snapshot": technical_snapshot,
            "available_tickers": sorted(list(tech_store.keys())),
        },

        "options": {
            "rows_found": len(rows),
            "best_strategy": strategy,
            "strategy_alignment": strategy_alignment,
            "best_row": best_row,
            "options_score": options_score,
            "rows": rows[:10],
        },

        "market_hours": market_hours,

        "diagnostics": {
            "technical_snapshot_available": technical_available,
            "options_rows_found": len(rows),
            "decision_snapshot_available": bool(decision_snapshot),
            "safe_technical_file": str(_V22_SAFE_TECH_FILE),
            "decision_file": str(_V22_DECISION_FILE),
        }
    }

def _v22_default_tickers():
    tickers = set()
    try:
        tickers.update(_v22_load_technical_store().keys())
    except Exception:
        pass

    try:
        snap = _v22_load_decision_snapshot()
        rows = _v22_extract_rows_from_snapshot(snap)
        for r in rows:
            t = _v22_norm_ticker(r.get("ticker") or r.get("symbol") or r.get("underlying"))
            if t:
                tickers.add(t)
    except Exception:
        pass

    if not tickers:
        tickers.update(["QQQ", "SPY", "NVDA", "TSLA", "NFLX", "META", "TLT"])

    return sorted(list(tickers))

@app.get("/v22_trade_decision/{ticker}")
def v22_trade_decision(ticker: str):
    return _v22_build_trade_decision(ticker)

@app.get("/gpt_trade_decision/{ticker}")
def gpt_trade_decision(ticker: str):
    d = _v22_build_trade_decision(ticker)
    return {
        "ticker": d.get("ticker"),
        "decision": d.get("decision"),
        "final_state": d.get("final_state"),
        "can_operate": d.get("can_operate"),
        "main_blocker": d.get("main_blocker"),
        "action": d.get("action"),
        "executive_summary": d.get("executive_summary"),
        "technical_bias": (d.get("technical") or {}).get("bias"),
        "technical_score": (d.get("technical") or {}).get("score"),
        "technical_available": (d.get("technical") or {}).get("available"),
        "options_strategy": (d.get("options") or {}).get("best_strategy"),
        "options_score": (d.get("options") or {}).get("options_score"),
        "options_rows_found": (d.get("options") or {}).get("rows_found"),
        "market_hours": d.get("market_hours"),
        "engine": d.get("engine"),
        "generated_at": d.get("generated_at"),
    }

@app.get("/v22_trade_summary")
def v22_trade_summary():
    tickers = _v22_default_tickers()
    decisions = [_v22_build_trade_decision(t) for t in tickers]

    counts = {}
    for d in decisions:
        state = d.get("final_state") or "UNKNOWN"
        counts[state] = counts.get(state, 0) + 1

    entry_ready = [d for d in decisions if d.get("final_state") == "ENTRY_READY"]
    radar = [d for d in decisions if str(d.get("final_state") or "").startswith("RADAR")]
    waiting = [d for d in decisions if str(d.get("final_state") or "").startswith("WAIT")]
    conflicts = [d for d in decisions if d.get("final_state") in ["TECHNICAL_CONFLICT", "BLOCKED"]]

    def rank(d):
        tech_score = (d.get("technical") or {}).get("score") or 0
        opt_score = (d.get("options") or {}).get("options_score") or 0
        state = d.get("final_state")
        bonus = 0
        if state == "ENTRY_READY":
            bonus += 1000
        elif str(state or "").startswith("RADAR"):
            bonus += 500
        return bonus + float(tech_score or 0) + float(opt_score or 0)

    ranked = sorted(decisions, key=rank, reverse=True)
    best = ranked[0] if ranked else None

    return {
        "engine": "V22_UNIFIED_TRADING_DECISION_ENGINE",
        "generated_at": _v22_now(),
        "status": "OK",
        "tickers": tickers,
        "counts": counts,
        "best": {
            "ticker": best.get("ticker"),
            "state": best.get("final_state"),
            "can_operate": best.get("can_operate"),
            "summary": best.get("executive_summary"),
        } if best else None,
        "entry_ready_count": len(entry_ready),
        "radar_count": len(radar),
        "waiting_count": len(waiting),
        "conflict_count": len(conflicts),
        "top": [
            {
                "ticker": d.get("ticker"),
                "state": d.get("final_state"),
                "can_operate": d.get("can_operate"),
                "technical_bias": (d.get("technical") or {}).get("bias"),
                "technical_score": (d.get("technical") or {}).get("score"),
                "strategy": (d.get("options") or {}).get("best_strategy"),
                "options_score": (d.get("options") or {}).get("options_score"),
                "blocker": d.get("main_blocker"),
                "action": d.get("action"),
            }
            for d in ranked[:10]
        ],
        "market_hours": _v22_get_market_hours(),
    }

@app.get("/gpt_trade_summary")
def gpt_trade_summary():
    return v22_trade_summary()

@app.get("/v22_system_status")
def v22_system_status():
    tech_store = _v22_load_technical_store()
    decision_snapshot = _v22_load_decision_snapshot()
    rows = _v22_extract_rows_from_snapshot(decision_snapshot)
    mh = _v22_get_market_hours()

    return {
        "engine": "V22_UNIFIED_TRADING_DECISION_ENGINE",
        "generated_at": _v22_now(),
        "status": "OK",
        "technical_snapshot_available": bool(tech_store),
        "technical_tickers": sorted(list(tech_store.keys())),
        "technical_count": len(tech_store),
        "decision_snapshot_available": bool(decision_snapshot),
        "option_rows_detected": len(rows),
        "market_hours": mh,
        "endpoints": {
            "v22_trade_summary": "/v22_trade_summary",
            "v22_trade_decision_example": "/v22_trade_decision/QQQ",
            "gpt_trade_summary": "/gpt_trade_summary",
            "gpt_trade_decision_example": "/gpt_trade_decision/QQQ",
        }
    }
'''

if "V22 — UNIFIED TRADING DECISION ENGINE" not in s:
    s = s.rstrip() + "\n\n" + block + "\n"

p.write_text(s)
