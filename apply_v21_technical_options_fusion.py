from pathlib import Path

main = Path("app/main.py")
m = main.read_text()

v21_block = r'''
# ============================================================
# SUPER ENGINE BOLSA — V21 TECHNICAL + OPTIONS FUSION
# ============================================================

import json as _v21_json
from pathlib import Path as _v21_Path
from datetime import datetime as _v21_datetime, timezone as _v21_timezone

def _v21_safe_float(value, default=None):
    try:
        if value is None:
            return default
        if value == "":
            return default
        return float(value)
    except Exception:
        return default

def _v21_safe_int(value, default=0):
    try:
        if value is None:
            return default
        if value == "":
            return default
        return int(float(value))
    except Exception:
        return default

def _v21_candidate_technical_paths():
    return [
        _v21_Path("runtime/technical_snapshot.json"),
        _v21_Path("runtime/technical_snapshot_v15_1.json"),
        _v21_Path("runtime/latest_technical_snapshot.json"),
        _v21_Path("/tmp/technical_snapshot.json"),
        _v21_Path("/tmp/technical_snapshot_v15_1.json"),
        _v21_Path("/tmp/latest_technical_snapshot.json"),
    ]

def _v21_load_technical_store():
    """
    V21:
    Carga el technical snapshot desde las ubicaciones probables.
    También intenta usar funciones globales existentes si el backend ya las tiene.
    """
    # 1) Intentar funciones existentes del app si están definidas
    possible_functions = [
        "_get_latest_technical_snapshot",
        "get_latest_technical_snapshot",
        "_technical_snapshot_store",
        "_load_technical_snapshot",
    ]

    for fn_name in possible_functions:
        try:
            fn = globals().get(fn_name)
            if callable(fn):
                data = fn()
                if data:
                    return {
                        "available": True,
                        "source": f"function:{fn_name}",
                        "data": data,
                    }
        except Exception:
            pass

    # 2) Intentar variables globales existentes
    possible_vars = [
        "TECHNICAL_SNAPSHOT_STORE",
        "technical_snapshot_store",
        "latest_technical_snapshot",
        "LATEST_TECHNICAL_SNAPSHOT",
    ]

    for var_name in possible_vars:
        try:
            data = globals().get(var_name)
            if data:
                return {
                    "available": True,
                    "source": f"global:{var_name}",
                    "data": data,
                }
        except Exception:
            pass

    # 3) Intentar archivos runtime/tmp
    for p in _v21_candidate_technical_paths():
        try:
            if p.exists():
                raw = p.read_text()
                if raw.strip():
                    data = _v21_json.loads(raw)
                    return {
                        "available": True,
                        "source": str(p),
                        "data": data,
                    }
        except Exception:
            pass

    return {
        "available": False,
        "source": None,
        "data": None,
    }

def _v21_extract_technical_by_ticker():
    store = _v21_load_technical_store()
    data = store.get("data")

    result = {}

    if not data:
        return {
            "available": False,
            "source": store.get("source"),
            "by_ticker": {},
            "raw": data,
        }

    try:
        # Caso A: payload directo de un solo ticker
        if isinstance(data, dict) and data.get("ticker"):
            t = str(data.get("ticker")).upper()
            result[t] = data

        # Caso B: dict con technical_snapshot
        if isinstance(data, dict) and isinstance(data.get("technical_snapshot"), dict):
            ts = data.get("technical_snapshot")
            if ts.get("ticker"):
                result[str(ts.get("ticker")).upper()] = ts

        # Caso C: dict por ticker
        if isinstance(data, dict):
            for k, v in data.items():
                if isinstance(v, dict):
                    if v.get("ticker"):
                        result[str(v.get("ticker")).upper()] = v
                    elif str(k).isalpha() and len(str(k)) <= 6:
                        vv = dict(v)
                        vv.setdefault("ticker", str(k).upper())
                        result[str(k).upper()] = vv

        # Caso D: lista de snapshots
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and item.get("ticker"):
                    result[str(item.get("ticker")).upper()] = item

        # Caso E: payload con rows/items
        if isinstance(data, dict):
            for key in ["rows", "items", "snapshots", "data"]:
                rows = data.get(key)
                if isinstance(rows, list):
                    for item in rows:
                        if isinstance(item, dict) and item.get("ticker"):
                            result[str(item.get("ticker")).upper()] = item
    except Exception:
        pass

    return {
        "available": bool(result),
        "source": store.get("source"),
        "by_ticker": result,
        "raw": data,
    }

def _v21_technical_bias(ts):
    if not isinstance(ts, dict) or not ts:
        return {
            "bias": "UNKNOWN",
            "confirmation": False,
            "score": 0,
            "reason": "Sin technical snapshot disponible para el ticker.",
        }

    trend = str(ts.get("trend") or ts.get("trend_label") or "").lower()
    trend_code = _v21_safe_float(ts.get("trend_code"), None)
    score = _v21_safe_float(ts.get("score"), None)
    rsi = _v21_safe_float(ts.get("rsi"), None)
    adx = _v21_safe_float(ts.get("adx"), None)
    range_breakout = ts.get("range_breakout")
    support_near = ts.get("support_near")
    resistance_near = ts.get("resistance_near")
    vwap_position = str(ts.get("vwap_position") or "").lower()
    vwap_position_code = _v21_safe_float(ts.get("vwap_position_code"), None)
    volume_relative = _v21_safe_float(ts.get("volume_relative"), None)
    event_risk = bool(ts.get("event_risk") or False)
    earnings_soon = bool(ts.get("earnings_soon") or False)

    bullish_points = 0
    bearish_points = 0
    neutral_points = 0
    reasons = []

    # Trend
    if "bull" in trend or trend_code == 1:
        bullish_points += 2
        reasons.append("tendencia alcista")
    elif "bear" in trend or trend_code == -1:
        bearish_points += 2
        reasons.append("tendencia bajista")
    elif "neutral" in trend or trend_code == 0:
        neutral_points += 1
        reasons.append("tendencia neutral")

    # Score técnico
    if score is not None:
        if score >= 75:
            bullish_points += 1
            reasons.append(f"score técnico fuerte ({score})")
        elif score <= 35:
            bearish_points += 1
            reasons.append(f"score técnico débil ({score})")
        else:
            neutral_points += 1
            reasons.append(f"score técnico mixto ({score})")

    # RSI
    if rsi is not None:
        if 45 <= rsi <= 65:
            neutral_points += 1
            reasons.append(f"RSI saludable/neutral ({rsi})")
        elif rsi < 35:
            bullish_points += 1
            reasons.append(f"RSI en zona baja/sobreventa relativa ({rsi})")
        elif rsi > 70:
            bearish_points += 1
            reasons.append(f"RSI extendido/sobrecompra ({rsi})")

    # ADX
    if adx is not None:
        if adx >= 25:
            if bullish_points >= bearish_points:
                bullish_points += 1
                reasons.append(f"ADX confirma fuerza de tendencia ({adx})")
            else:
                bearish_points += 1
                reasons.append(f"ADX confirma presión direccional ({adx})")
        elif adx < 20:
            neutral_points += 1
            reasons.append(f"ADX bajo/rango ({adx})")

    # VWAP
    if "above" in vwap_position or vwap_position_code == 1:
        bullish_points += 1
        reasons.append("precio sobre VWAP")
    elif "below" in vwap_position or vwap_position_code == -1:
        bearish_points += 1
        reasons.append("precio bajo VWAP")
    elif "near" in vwap_position or vwap_position_code == 0:
        neutral_points += 1
        reasons.append("precio cerca de VWAP")

    # Breakout / soportes
    if range_breakout is True or str(range_breakout).lower() == "true":
        bullish_points += 1
        reasons.append("ruptura de rango detectada")
    if support_near is True or str(support_near).lower() == "true":
        bullish_points += 1
        reasons.append("soporte cercano")
    if resistance_near is True or str(resistance_near).lower() == "true":
        bearish_points += 1
        reasons.append("resistencia cercana")

    # Volumen
    if volume_relative is not None:
        if volume_relative >= 1.5:
            if bullish_points >= bearish_points:
                bullish_points += 1
            else:
                bearish_points += 1
            reasons.append(f"volumen relativo elevado ({volume_relative})")
        elif volume_relative < 0.8:
            neutral_points += 1
            reasons.append(f"volumen relativo bajo ({volume_relative})")

    # Eventos
    if event_risk or earnings_soon:
        bearish_points += 2
        reasons.append("riesgo de evento/earnings")

    if bullish_points > bearish_points and bullish_points >= 2:
        bias = "BULLISH"
    elif bearish_points > bullish_points and bearish_points >= 2:
        bias = "BEARISH"
    elif neutral_points >= 1:
        bias = "NEUTRAL"
    else:
        bias = "UNKNOWN"

    confidence_score = max(0, min(100, (bullish_points - bearish_points + 4) * 12.5))
    if bias == "NEUTRAL":
        confidence_score = max(40, min(65, confidence_score))
    if bias == "UNKNOWN":
        confidence_score = 0

    confirmation = bias in ["BULLISH", "NEUTRAL"] and not event_risk and not earnings_soon

    return {
        "bias": bias,
        "confirmation": bool(confirmation),
        "score": round(confidence_score, 1),
        "bullish_points": bullish_points,
        "bearish_points": bearish_points,
        "neutral_points": neutral_points,
        "reason": "; ".join(reasons) if reasons else "Technical snapshot sin señales suficientes.",
    }

def _v21_strategy_technical_fit(strategy, technical_bias):
    strategy = str(strategy or "").upper()
    bias = str(technical_bias or "UNKNOWN").upper()

    if strategy == "NAKED_PUT":
        if bias == "BULLISH":
            return {
                "fit": "STRONG_FIT",
                "score_adjustment": 15,
                "reason": "Naked Put favorecida por sesgo técnico alcista.",
            }
        if bias == "NEUTRAL":
            return {
                "fit": "ACCEPTABLE_FIT",
                "score_adjustment": 5,
                "reason": "Naked Put aceptable con técnico neutral/rango.",
            }
        if bias == "BEARISH":
            return {
                "fit": "POOR_FIT",
                "score_adjustment": -25,
                "reason": "Naked Put desfavorecida por sesgo técnico bajista.",
            }

    if strategy == "COVERED_CALL":
        if bias == "BEARISH":
            return {
                "fit": "STRONG_FIT",
                "score_adjustment": 15,
                "reason": "Covered Call favorecida por sesgo técnico bajista o de techo.",
            }
        if bias == "NEUTRAL":
            return {
                "fit": "ACCEPTABLE_FIT",
                "score_adjustment": 8,
                "reason": "Covered Call aceptable con técnico neutral/rango.",
            }
        if bias == "BULLISH":
            return {
                "fit": "CAUTION",
                "score_adjustment": -8,
                "reason": "Covered Call requiere cautela si el activo está muy alcista.",
            }

    return {
        "fit": "UNKNOWN_FIT",
        "score_adjustment": 0,
        "reason": "Sin regla técnica específica para esta estrategia.",
    }

def _v21_fuse_row(row, technical_by_ticker):
    r = dict(row or {})
    ticker = str(r.get("ticker") or "").upper()
    strategy = str(r.get("strategy") or "").upper()

    ts = technical_by_ticker.get(ticker)
    tech = _v21_technical_bias(ts)
    fit = _v21_strategy_technical_fit(strategy, tech.get("bias"))

    base_score = _v21_safe_float(r.get("score"), 0) or 0
    adjustment = _v21_safe_float(fit.get("score_adjustment"), 0) or 0
    combined_score = max(0, min(100, base_score + adjustment))

    can_operate = bool(r.get("can_operate"))
    operational_state = r.get("operational_state") or r.get("decision")
    technical_confirmation = bool(tech.get("confirmation"))

    if can_operate and technical_confirmation and combined_score >= 80:
        final_state = "ENTRY_CONFIRMED"
        final_action = "Oportunidad técnicamente confirmada. Validar precio límite, tamaño y riesgo antes de ejecutar."
    elif str(operational_state).upper() in ["MARKET_CLOSED_OR_NOT_LIQUID_YET"]:
        final_state = "WAIT_MARKET_OPEN"
        final_action = "No operar ahora. Esperar ventana confiable de opciones y revalidar técnico."
    elif str(operational_state).upper() in ["WAIT_LIQUIDITY"]:
        final_state = "WAIT_LIQUIDITY"
        final_action = "Esperar bid/ask y spread real antes de considerar entrada."
    elif str(operational_state).upper() in ["WAIT_GREEKS"]:
        final_state = "WAIT_GREEKS"
        final_action = "Esperar griegas completas antes de considerar entrada."
    elif tech.get("bias") == "BEARISH" and strategy == "NAKED_PUT":
        final_state = "TECHNICAL_CONFLICT"
        final_action = "No operar Naked Put hasta que mejore el técnico o exista soporte confirmado."
    elif tech.get("bias") == "BULLISH" and strategy == "COVERED_CALL":
        final_state = "TECHNICAL_CAUTION"
        final_action = "Covered Call con cautela: técnico alcista puede limitar upside si se vende call muy cerca."
    elif combined_score >= 80:
        final_state = "RADAR_TECH_OK"
        final_action = "Mantener en radar. Técnico aceptable, pero falta confirmación operativa."
    elif combined_score >= 60:
        final_state = "RADAR_MIXED"
        final_action = "Mantener en observación. Señal mixta entre opciones y técnico."
    else:
        final_state = "LOW_PRIORITY"
        final_action = "Baja prioridad por score combinado o falta de confirmación técnica."

    r["technical_snapshot_available"] = bool(ts)
    r["technical_bias"] = tech.get("bias")
    r["technical_confirmation"] = tech.get("confirmation")
    r["technical_score"] = tech.get("score")
    r["technical_reason"] = tech.get("reason")
    r["strategy_technical_fit"] = fit.get("fit")
    r["strategy_technical_reason"] = fit.get("reason")
    r["combined_score"] = round(combined_score, 1)
    r["fusion_state"] = final_state
    r["fusion_action"] = final_action

    return r

def _v21_fusion_snapshot():
    base = _v19_safe_data()
    try:
        base = _v20_enrich_snapshot(base)
    except Exception:
        pass

    technical = _v21_extract_technical_by_ticker()
    technical_by_ticker = technical.get("by_ticker", {}) or {}

    top = base.get("top") or []
    fused_top = [_v21_fuse_row(row, technical_by_ticker) for row in top]
    fused_top = sorted(
        fused_top,
        key=lambda x: (
            _v21_safe_float(x.get("combined_score"), 0) or 0,
            _v21_safe_float(x.get("score"), 0) or 0,
        ),
        reverse=True,
    )

    best = fused_top[0] if fused_top else None

    counts = {
        "ENTRY_CONFIRMED": 0,
        "RADAR_TECH_OK": 0,
        "RADAR_MIXED": 0,
        "TECHNICAL_CONFLICT": 0,
        "TECHNICAL_CAUTION": 0,
        "WAIT_MARKET_OPEN": 0,
        "WAIT_LIQUIDITY": 0,
        "WAIT_GREEKS": 0,
        "LOW_PRIORITY": 0,
    }

    for row in fused_top:
        state = row.get("fusion_state") or "LOW_PRIORITY"
        counts[state] = counts.get(state, 0) + 1

    by_ticker = {}
    for row in fused_top:
        t = row.get("ticker") or "UNKNOWN"
        if t not in by_ticker:
            by_ticker[t] = {
                "ticker": t,
                "total": 0,
                "best": None,
                "technical_bias": row.get("technical_bias"),
                "technical_confirmation": row.get("technical_confirmation"),
                "avg_combined_score": 0,
                "states": {},
            }
        by_ticker[t]["total"] += 1
        by_ticker[t]["states"][row.get("fusion_state")] = by_ticker[t]["states"].get(row.get("fusion_state"), 0) + 1
        if by_ticker[t]["best"] is None or (_v21_safe_float(row.get("combined_score"), 0) or 0) > (_v21_safe_float(by_ticker[t]["best"].get("combined_score"), 0) or 0):
            by_ticker[t]["best"] = row

    for t, item in by_ticker.items():
        scores = [
            _v21_safe_float(r.get("combined_score"), 0) or 0
            for r in fused_top
            if r.get("ticker") == t
        ]
        item["avg_combined_score"] = round(sum(scores) / len(scores), 1) if scores else 0

    if best:
        executive = (
            f"Mejor oportunidad fusionada: {best.get('ticker')} / {best.get('strategy')} "
            f"con estado {best.get('fusion_state')} y score combinado {best.get('combined_score')}. "
            f"{best.get('fusion_action')}"
        )
    else:
        executive = "No hay oportunidades fusionadas disponibles. Revisar snapshot IBKR y technical snapshot."

    return {
        "engine": "V21_TECHNICAL_OPTIONS_FUSION",
        "status": "OK" if base.get("health", {}).get("snapshot_available") else "NO_SNAPSHOT",
        "generated_at": _v21_datetime.now(_v21_timezone.utc).isoformat(),
        "market_hours": base.get("market_hours"),
        "technical_snapshot_available": technical.get("available"),
        "technical_snapshot_source": technical.get("source"),
        "technical_tickers": sorted(list(technical_by_ticker.keys())),
        "summary": base.get("summary", {}),
        "fusion_counts": counts,
        "best_fusion_opportunity": best,
        "executive_conclusion": executive,
        "top": fused_top[:30],
        "by_ticker": list(by_ticker.values()),
        "health": base.get("health", {}),
    }

@app.get("/fusion_desk")
def fusion_desk():
    return _v21_fusion_snapshot()

@app.get("/fusion_ticker/{ticker}")
def fusion_ticker(ticker: str):
    data = _v21_fusion_snapshot()
    t = str(ticker or "").upper().strip()
    rows = [r for r in data.get("top", []) if str(r.get("ticker", "")).upper() == t]
    best = rows[0] if rows else None

    return {
        "engine": "V21_TECHNICAL_OPTIONS_FUSION",
        "ticker": t,
        "status": "OK" if rows else "NO_ROWS_FOR_TICKER",
        "market_hours": data.get("market_hours"),
        "technical_snapshot_available": data.get("technical_snapshot_available"),
        "technical_tickers": data.get("technical_tickers"),
        "best": best,
        "rows": rows,
        "executive_conclusion": (
            f"{t}: mejor oportunidad {best.get('strategy')} con estado {best.get('fusion_state')} "
            f"y score combinado {best.get('combined_score')}. {best.get('fusion_action')}"
            if best else f"No hay oportunidades fusionadas para {t}."
        ),
    }

@app.get("/gpt_fusion_summary")
def gpt_fusion_summary():
    data = _v21_fusion_snapshot()
    best = data.get("best_fusion_opportunity") or {}

    compact_top = []
    for row in data.get("top", [])[:5]:
        compact_top.append({
            "ticker": row.get("ticker"),
            "strategy": row.get("strategy"),
            "decision": row.get("decision"),
            "operational_state": row.get("operational_state"),
            "technical_bias": row.get("technical_bias"),
            "technical_confirmation": row.get("technical_confirmation"),
            "strategy_technical_fit": row.get("strategy_technical_fit"),
            "score": row.get("score"),
            "technical_score": row.get("technical_score"),
            "combined_score": row.get("combined_score"),
            "fusion_state": row.get("fusion_state"),
            "can_operate": row.get("can_operate"),
            "fusion_action": row.get("fusion_action"),
        })

    return {
        "engine": "V21_TECHNICAL_OPTIONS_FUSION",
        "status": data.get("status"),
        "market_hours": data.get("market_hours"),
        "technical_snapshot_available": data.get("technical_snapshot_available"),
        "technical_tickers": data.get("technical_tickers"),
        "fusion_counts": data.get("fusion_counts"),
        "best": {
            "ticker": best.get("ticker"),
            "strategy": best.get("strategy"),
            "fusion_state": best.get("fusion_state"),
            "combined_score": best.get("combined_score"),
            "technical_bias": best.get("technical_bias"),
            "technical_confirmation": best.get("technical_confirmation"),
            "can_operate": best.get("can_operate"),
            "fusion_action": best.get("fusion_action"),
            "technical_reason": best.get("technical_reason"),
            "strategy_technical_reason": best.get("strategy_technical_reason"),
        } if best else None,
        "top_5": compact_top,
        "executive_conclusion": data.get("executive_conclusion"),
        "health": data.get("health"),
    }
'''

if "V21 TECHNICAL + OPTIONS FUSION" not in m:
    m = m.rstrip() + "\n\n" + v21_block + "\n"

# Registrar rutas si existe endpoint de catálogo/debug routes
# No es indispensable; las rutas FastAPI ya quedan activas por @app.get.

# Mensaje viejo V18 -> mensaje genérico
m = m.replace(
    "No hay snapshot V18 disponible todavía. Corre ibkr_bridge.py para generar el último decision desk.",
    "No hay snapshot operativo disponible todavía. Corre ibkr_bridge.py para generar el último decision desk."
)

m = m.replace(
    "No hay snapshot V18 disponible todavía.",
    "No hay snapshot operativo disponible todavía."
)

main.write_text(m)
