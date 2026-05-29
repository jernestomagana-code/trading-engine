from pathlib import Path

main = Path("app/main.py")
m = main.read_text()

v20_block = r'''
# ============================================================
# SUPER ENGINE BOLSA — V20 MARKET HOURS & LIQUIDITY INTELLIGENCE
# ============================================================

from datetime import datetime as _v20_datetime, timezone as _v20_timezone, time as _v20_time
try:
    from zoneinfo import ZoneInfo as _v20_ZoneInfo
except Exception:
    _v20_ZoneInfo = None

def _v20_now_ny():
    try:
        if _v20_ZoneInfo:
            return _v20_datetime.now(_v20_ZoneInfo("America/New_York"))
    except Exception:
        pass
    return _v20_datetime.now(_v20_timezone.utc)

def _v20_market_hours_status():
    """
    V20:
    Determina estado simple de mercado USA.
    No reemplaza calendario oficial de feriados, pero mejora muchísimo la lectura
    respecto a bid/ask ausente fuera de horario.
    """
    now = _v20_now_ny()
    weekday = now.weekday()  # Monday=0, Sunday=6

    market_open = _v20_time(9, 30)
    market_close = _v20_time(16, 0)
    option_liquidity_start = _v20_time(9, 35)
    option_liquidity_end = _v20_time(15, 55)

    is_weekend = weekday >= 5
    current_time = now.time()

    if is_weekend:
        status = "WEEKEND_CLOSED"
        is_open = False
        options_expected = False
        next_check = "Próxima sesión hábil, después de 09:35 ET."
        label = "Mercado cerrado por fin de semana"
    elif current_time < market_open:
        status = "PRE_MARKET"
        is_open = False
        options_expected = False
        next_check = "Revisar después de 09:35 ET."
        label = "Pre-market: opciones aún no confiables"
    elif market_open <= current_time < option_liquidity_start:
        status = "OPENING_NOISE"
        is_open = True
        options_expected = False
        next_check = "Revisar después de 09:35 ET."
        label = "Apertura: esperar liquidez inicial"
    elif option_liquidity_start <= current_time <= option_liquidity_end:
        status = "REGULAR_OPTIONS_SESSION"
        is_open = True
        options_expected = True
        next_check = "Datos deberían ser operables si hay liquidez."
        label = "Mercado abierto: opciones en ventana operable"
    elif option_liquidity_end < current_time <= market_close:
        status = "LATE_SESSION"
        is_open = True
        options_expected = True
        next_check = "Precaución: cerca del cierre, spreads pueden abrirse."
        label = "Mercado abierto cerca del cierre"
    else:
        status = "AFTER_HOURS"
        is_open = False
        options_expected = False
        next_check = "Revisar próxima sesión después de 09:35 ET."
        label = "After-hours: opciones no confiables"

    return {
        "status": status,
        "label": label,
        "is_regular_market_open": bool(is_open),
        "options_bidask_expected": bool(options_expected),
        "new_york_time": now.isoformat(),
        "next_check": next_check,
    }

def _v20_row_operational_reason(row, market_status=None):
    """
    Interpreta por qué una fila no es operable.
    """
    market_status = market_status or _v20_market_hours_status()
    decision = str(row.get("decision") or "").upper()
    data_quality = str(row.get("data_quality") or "")
    missing = row.get("missing_confirmations") or []

    if isinstance(missing, str):
        missing_list = [x.strip() for x in missing.split(",") if x.strip()]
    elif isinstance(missing, list):
        missing_list = [str(x).strip() for x in missing if str(x).strip()]
    else:
        missing_list = []

    can_operate = bool(row.get("can_operate"))

    has_bidask_issue = (
        "bid_ask" in missing_list
        or "spread" in missing_list
        or "NO_BIDASK" in data_quality
        or "PRICE_ONLY" in data_quality
    )

    has_greeks_issue = (
        "greeks" in missing_list
        or "delta" in missing_list
        or "iv" in missing_list
        or "WAIT_GREEKS" in decision
        or "NO_GREEKS" in data_quality
    )

    if can_operate:
        return {
            "operational_state": "ENTRY_READY",
            "severity": "green",
            "reason": "Oportunidad operable. Validar tamaño, riesgo y precio límite antes de ejecutar.",
            "next_action": "Validar orden sugerida y gestión de riesgo.",
        }

    if not market_status.get("options_bidask_expected") and has_bidask_issue:
        return {
            "operational_state": "MARKET_CLOSED_OR_NOT_LIQUID_YET",
            "severity": "gray",
            "reason": "La falta de bid/ask o spread es esperada porque las opciones no están en una ventana confiable.",
            "next_action": market_status.get("next_check"),
        }

    if has_bidask_issue:
        return {
            "operational_state": "WAIT_LIQUIDITY",
            "severity": "orange",
            "reason": "La oportunidad tiene score alto, pero falta confirmar bid/ask y spread real.",
            "next_action": "Esperar bid/ask completo y spread razonable antes de operar.",
        }

    if has_greeks_issue:
        return {
            "operational_state": "WAIT_GREEKS",
            "severity": "orange",
            "reason": "Faltan griegas o datos críticos de opciones para validar riesgo.",
            "next_action": "Esperar actualización de delta, IV y griegas.",
        }

    if decision == "RADAR":
        return {
            "operational_state": "RADAR",
            "severity": "yellow",
            "reason": "Oportunidad interesante, pero aún no cumple todas las reglas de entrada.",
            "next_action": "Mantener en radar.",
        }

    if decision == "BLOCKED":
        return {
            "operational_state": "BLOCKED",
            "severity": "red",
            "reason": "Bloqueada por reglas de seguridad, calidad o riesgo.",
            "next_action": "No operar.",
        }

    return {
        "operational_state": "WAIT_DATA",
        "severity": "gray",
        "reason": "Faltan datos suficientes para clasificar la oportunidad.",
        "next_action": "Esperar siguiente ciclo.",
    }

def _v20_enrich_rows(rows):
    market_status = _v20_market_hours_status()
    enriched = []
    for row in rows or []:
        try:
            r = dict(row)
            op = _v20_row_operational_reason(r, market_status)
            r["market_hours"] = market_status
            r["operational_state"] = op.get("operational_state")
            r["operational_reason"] = op.get("reason")
            r["operational_next_action"] = op.get("next_action")
            r["operational_severity"] = op.get("severity")
            enriched.append(r)
        except Exception:
            enriched.append(row)
    return enriched

def _v20_enrich_snapshot(data):
    try:
        d = dict(data or {})
        market_status = _v20_market_hours_status()
        d["market_hours"] = market_status

        top = d.get("top") or []
        enriched_top = _v20_enrich_rows(top)
        d["top"] = enriched_top

        nba = d.get("next_best_action")
        if isinstance(nba, dict):
            nba2 = dict(nba)
            op = _v20_row_operational_reason(nba2, market_status)
            nba2["market_hours"] = market_status
            nba2["operational_state"] = op.get("operational_state")
            nba2["operational_reason"] = op.get("reason")
            nba2["operational_next_action"] = op.get("next_action")
            nba2["operational_severity"] = op.get("severity")

            if not nba2.get("can_operate") and op.get("operational_state") == "MARKET_CLOSED_OR_NOT_LIQUID_YET":
                nba2["recommendation"] = (
                    "Mantener en radar. No operar ahora porque las opciones no están en una ventana "
                    "confiable para bid/ask. " + str(market_status.get("next_check"))
                )
            elif not nba2.get("can_operate") and op.get("operational_state") == "WAIT_LIQUIDITY":
                nba2["recommendation"] = (
                    "Mantener en radar. No operar directo hasta confirmar liquidez real: bid/ask y spread."
                )

            d["next_best_action"] = nba2

        d.setdefault("health", {})
        d["health"]["market_hours_status"] = market_status.get("status")
        d["health"]["options_bidask_expected"] = market_status.get("options_bidask_expected")
        d["health"]["market_hours_label"] = market_status.get("label")
        return d
    except Exception:
        return data

@app.get("/market_hours")
def market_hours():
    return {
        "engine": "V20_MARKET_HOURS_LIQUIDITY_INTELLIGENCE",
        "market_hours": _v20_market_hours_status(),
    }

@app.get("/liquidity_desk")
def liquidity_desk():
    data = _v19_safe_data()
    data = _v20_enrich_snapshot(data)
    market_status = data.get("market_hours", {})
    top = data.get("top", []) or []

    counts = {
        "ENTRY_READY": 0,
        "MARKET_CLOSED_OR_NOT_LIQUID_YET": 0,
        "WAIT_LIQUIDITY": 0,
        "WAIT_GREEKS": 0,
        "RADAR": 0,
        "WAIT_DATA": 0,
        "BLOCKED": 0,
    }

    for row in top:
        state = row.get("operational_state") or "WAIT_DATA"
        counts[state] = counts.get(state, 0) + 1

    return {
        "engine": "V20_MARKET_HOURS_LIQUIDITY_INTELLIGENCE",
        "status": "OK",
        "market_hours": market_status,
        "operational_counts": counts,
        "best_opportunity": data.get("next_best_action"),
        "top": top[:20],
        "summary": data.get("summary", {}),
        "health": data.get("health", {}),
    }
'''

if "V20 MARKET HOURS & LIQUIDITY INTELLIGENCE" not in m:
    m = m.rstrip() + "\n\n" + v20_block + "\n"

# Patch V19 safe data to auto-enrich if possible
old = '''def gpt_decision_summary():
    data = _v19_safe_data()
    summary = data.get("summary", {}) or {}'''
new = '''def gpt_decision_summary():
    data = _v19_safe_data()
    try:
        data = _v20_enrich_snapshot(data)
    except Exception:
        pass
    summary = data.get("summary", {}) or {}'''

if old in m and "data = _v20_enrich_snapshot(data)" not in m[m.find("def gpt_decision_summary()"):m.find("def system_status()")]:
    m = m.replace(old, new, 1)

old = '''def system_status():
    data = _v19_safe_data()
    freshness = _v19_freshness(data)'''
new = '''def system_status():
    data = _v19_safe_data()
    try:
        data = _v20_enrich_snapshot(data)
    except Exception:
        pass
    freshness = _v19_freshness(data)'''

if old in m and "data = _v20_enrich_snapshot(data)" not in m[m.find("def system_status()"):]:
    m = m.replace(old, new, 1)

# Patch dashboard_decision with V20 enrichment
old = '''def dashboard_decision():
    data = _v19_safe_data()
    summary = data.get("summary", {}) or {}'''
new = '''def dashboard_decision():
    data = _v19_safe_data()
    try:
        data = _v20_enrich_snapshot(data)
    except Exception:
        pass
    summary = data.get("summary", {}) or {}'''

if old in m and "data = _v20_enrich_snapshot(data)" not in m[m.find("def dashboard_decision()"):m.find("def dashboard_ticker")]:
    m = m.replace(old, new, 1)

# Patch dashboard_ticker with V20 enrichment
old = '''def dashboard_ticker(ticker: str):
    data = _v19_safe_data()
    t = str(ticker or "").upper().strip()'''
new = '''def dashboard_ticker(ticker: str):
    data = _v19_safe_data()
    try:
        data = _v20_enrich_snapshot(data)
    except Exception:
        pass
    t = str(ticker or "").upper().strip()'''

if old in m and "data = _v20_enrich_snapshot(data)" not in m[m.find("def dashboard_ticker"):m.find("def gpt_decision_summary")]:
    m = m.replace(old, new, 1)

# Improve dashboard table columns with operational state if exact table function exists
m = m.replace(
'''          <td>{_v19_escape(missing_text)}</td>
          <td>{_v19_escape(can_operate)}</td>
          <td class="small">{_v19_escape(action)}</td>''',
'''          <td>{_v19_escape(row.get("operational_state") or missing_text)}</td>
          <td>{_v19_escape(can_operate)}</td>
          <td class="small">{_v19_escape(row.get("operational_next_action") or action)}</td>'''
)

# Improve GPT output
m = m.replace(
'''"freshness": freshness,
        "market_call": call.get("market_call"),''',
'''"freshness": freshness,
        "market_hours": data.get("market_hours"),
        "market_call": call.get("market_call"),'''
)

# Improve top_3 output
m = m.replace(
'''"reason": row.get("reason"),
        })''',
'''"reason": row.get("reason"),
            "operational_state": row.get("operational_state"),
            "operational_reason": row.get("operational_reason"),
            "operational_next_action": row.get("operational_next_action"),
        })''',
1
)

# Improve best opportunity output
m = m.replace(
'''"reason": nba.get("reason"),
        } if nba else None,''',
'''"reason": nba.get("reason"),
            "operational_state": nba.get("operational_state"),
            "operational_reason": nba.get("operational_reason"),
            "operational_next_action": nba.get("operational_next_action"),
        } if nba else None,''',
1
)

main.write_text(m)
