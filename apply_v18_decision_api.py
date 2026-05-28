from pathlib import Path

bridge = Path("ibkr_bridge.py")
main = Path("app/main.py")

s = bridge.read_text()

# ============================================================
# 1) Subir versión visual del bridge
# ============================================================

s = s.replace("V17_3C_CLEAN_CONSOLE", "V18_OPERATIONAL_DECISION_API")

# ============================================================
# 2) Insertar helpers V18 en ibkr_bridge.py
# ============================================================

v18_block = r'''
# ============================================================
# SUPER ENGINE BOLSA — V18 OPERATIONAL DECISION API HELPERS
# ============================================================

import json as _v18_json
from pathlib import Path as _v18_Path
from datetime import datetime as _v18_datetime, timezone as _v18_timezone

V18_SNAPSHOT_PATH = _v18_Path("runtime/decision_desk_snapshot.json")

def v18_safe_float(value, default=0.0):
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default

def v18_normalize_decision(raw):
    try:
        d = str(raw or "").upper().strip()
    except Exception:
        d = ""

    if d in ["ENTRY", "ENTRY_OPPORTUNITY", "OPERAR", "TRADE"]:
        return "ENTRY"
    if d in ["MANAGE_POSITION", "MANAGE", "GESTION", "REVISAR_GESTION"]:
        return "MANAGE_POSITION"
    if d in ["RADAR", "WATCH", "PREPARATION", "PREPARACION"]:
        return "RADAR"
    if d in ["WAIT_FOR_GREEKS", "WAIT_GREEKS"]:
        return "WAIT_GREEKS"
    if d in ["WAIT_FOR_DATA", "MISSING_DATA", "WAIT_DATA"]:
        return "WAIT_DATA"
    if d in ["BLOCKED", "NO_TRADE", "REJECTED"]:
        return "BLOCKED"
    if d in ["ESPERAR", "WAIT"]:
        return "WAIT_DATA"

    return d or "WAIT_DATA"

def v18_missing_confirmations(row):
    missing = []

    quality = str(row.get("data_quality") or row.get("quality") or "").upper()
    decision = v18_normalize_decision(row.get("decision") or row.get("final_decision") or row.get("cap"))

    if "NO_BIDASK" in quality:
        missing.append("bid_ask")
        missing.append("spread")

    if "PRICE_ONLY" in quality:
        missing.append("greeks")
        missing.append("bid_ask")
        missing.append("spread")

    if decision == "WAIT_GREEKS":
        if "greeks" not in missing:
            missing.append("greeks")

    if decision == "WAIT_DATA":
        if "data_confirmation" not in missing:
            missing.append("data_confirmation")

    if row.get("price") in [None, "", "None"]:
        missing.append("price")

    # Deduplicar preservando orden
    final = []
    for x in missing:
        if x not in final:
            final.append(x)

    return final

def v18_can_operate(row):
    decision = v18_normalize_decision(row.get("decision") or row.get("final_decision") or row.get("cap"))
    missing = v18_missing_confirmations(row)
    score = v18_safe_float(row.get("score"), 0)

    if decision != "ENTRY":
        return False

    if score < 80:
        return False

    if missing:
        return False

    return True

def v18_recommendation(row):
    decision = v18_normalize_decision(row.get("decision") or row.get("final_decision") or row.get("cap"))
    missing = v18_missing_confirmations(row)
    can_operate = v18_can_operate(row)

    if can_operate:
        return "Posible operación. Validar tamaño, riesgo y confirmación final antes de ejecutar."

    if decision == "MANAGE_POSITION":
        return "Prioridad de gestión. Revisar posición abierta antes de abrir nuevas operaciones."

    if decision == "RADAR":
        if missing:
            return "Mantener en radar. No operar directo hasta confirmar: " + ", ".join(missing) + "."
        return "Mantener en radar. Aún no es entrada confirmada."

    if decision == "WAIT_GREEKS":
        return "Esperar. Faltan griegas o datos suficientes para validar la operación."

    if decision == "WAIT_DATA":
        return "Esperar. Faltan datos críticos o confirmación suficiente."

    if decision == "BLOCKED":
        return "Bloqueado. No operar bajo las condiciones actuales."

    return "Esperar. No hay ventaja operativa suficiente."

def v18_reason(row):
    decision = v18_normalize_decision(row.get("decision") or row.get("final_decision") or row.get("cap"))
    quality = str(row.get("data_quality") or row.get("quality") or "UNKNOWN")
    score = v18_safe_float(row.get("score"), 0)
    missing = v18_missing_confirmations(row)

    if decision == "RADAR" and score >= 80:
        if missing:
            return f"Score alto y datos parciales útiles, pero faltan confirmaciones: {', '.join(missing)}."
        return "Score alto, pero la señal permanece en radar y no en entrada."

    if decision == "WAIT_GREEKS":
        return "La oportunidad requiere griegas completas antes de tomar decisión."

    if decision == "WAIT_DATA":
        return "La oportunidad requiere más datos antes de tomar decisión."

    if decision == "BLOCKED":
        return "La operación fue bloqueada por calidad, liquidez, spread o reglas de seguridad."

    if decision == "ENTRY":
        return "La oportunidad cumple criterios principales de entrada, sujeto a gestión de riesgo."

    return f"Decisión {decision} con calidad de datos {quality}."

def v18_compact_row(row):
    decision = v18_normalize_decision(row.get("decision") or row.get("final_decision") or row.get("cap"))

    compact = {
        "ticker": str(row.get("ticker") or row.get("symbol") or "UNKNOWN"),
        "strategy": str(row.get("strategy") or row.get("strategy_hint") or row.get("setup") or "UNKNOWN"),
        "decision": decision,
        "score": v18_safe_float(row.get("score"), 0),
        "price": row.get("price") or row.get("mid") or row.get("last"),
        "data_quality": row.get("data_quality") or row.get("quality") or "UNKNOWN",
        "can_operate": False,
        "missing_confirmations": [],
        "recommendation": "",
        "reason": "",
    }

    compact["missing_confirmations"] = v18_missing_confirmations(compact | row)
    compact["can_operate"] = v18_can_operate(compact | row)
    compact["recommendation"] = v18_recommendation(compact | row)
    compact["reason"] = v18_reason(compact | row)

    return compact

def v18_priority_rank(row):
    decision = v18_normalize_decision(row.get("decision"))
    score = v18_safe_float(row.get("score"), 0)

    decision_weight = {
        "MANAGE_POSITION": 500,
        "ENTRY": 400,
        "RADAR": 300,
        "WAIT_GREEKS": 150,
        "WAIT_DATA": 100,
        "BLOCKED": 0,
    }.get(decision, 50)

    return decision_weight + score

def v18_build_decision_payload(rows=None):
    try:
        if rows is None:
            rows = []

        clean_rows = []
        seen = set()

        for row in rows:
            if not isinstance(row, dict):
                continue

            c = v18_compact_row(row)
            key = (
                c.get("ticker"),
                c.get("strategy"),
                c.get("decision"),
                str(c.get("price")),
                str(c.get("score")),
            )

            if key in seen:
                continue

            seen.add(key)
            clean_rows.append(c)

        clean_rows.sort(key=v18_priority_rank, reverse=True)

        summary = {
            "entry": sum(1 for r in clean_rows if r["decision"] == "ENTRY"),
            "manage_position": sum(1 for r in clean_rows if r["decision"] == "MANAGE_POSITION"),
            "radar": sum(1 for r in clean_rows if r["decision"] == "RADAR"),
            "wait_greeks": sum(1 for r in clean_rows if r["decision"] == "WAIT_GREEKS"),
            "wait_data": sum(1 for r in clean_rows if r["decision"] == "WAIT_DATA"),
            "blocked": sum(1 for r in clean_rows if r["decision"] == "BLOCKED"),
            "total": len(clean_rows),
        }

        by_ticker = {}
        by_strategy = {}

        for r in clean_rows:
            ticker = r["ticker"]
            strategy = r["strategy"]
            decision = r["decision"]

            by_ticker.setdefault(ticker, {
                "ticker": ticker,
                "total": 0,
                "entry": 0,
                "radar": 0,
                "wait_greeks": 0,
                "wait_data": 0,
                "blocked": 0,
                "best": None,
            })

            by_strategy.setdefault(strategy, {
                "strategy": strategy,
                "total": 0,
                "entry": 0,
                "radar": 0,
                "wait_greeks": 0,
                "wait_data": 0,
                "blocked": 0,
                "best": None,
            })

            for bucket in [by_ticker[ticker], by_strategy[strategy]]:
                bucket["total"] += 1
                if decision == "ENTRY":
                    bucket["entry"] += 1
                elif decision == "RADAR":
                    bucket["radar"] += 1
                elif decision == "WAIT_GREEKS":
                    bucket["wait_greeks"] += 1
                elif decision == "WAIT_DATA":
                    bucket["wait_data"] += 1
                elif decision == "BLOCKED":
                    bucket["blocked"] += 1

                if bucket["best"] is None or v18_priority_rank(r) > v18_priority_rank(bucket["best"]):
                    bucket["best"] = r

        next_best_action = clean_rows[0] if clean_rows else None

        if next_best_action:
            global_recommendation = next_best_action.get("recommendation")
        else:
            global_recommendation = "No hay oportunidades operativas disponibles en el último ciclo."

        payload = {
            "engine": "V18_OPERATIONAL_DECISION_API",
            "generated_at": _v18_datetime.now(_v18_timezone.utc).isoformat(),
            "summary": summary,
            "next_best_action": next_best_action,
            "recommendation": global_recommendation,
            "by_ticker": list(by_ticker.values()),
            "by_strategy": list(by_strategy.values()),
            "top": clean_rows[:20],
            "health": {
                "snapshot_available": True,
                "rows_captured": len(clean_rows),
                "can_operate_count": sum(1 for r in clean_rows if r.get("can_operate")),
            },
        }

        return payload

    except Exception as e:
        return {
            "engine": "V18_OPERATIONAL_DECISION_API",
            "generated_at": _v18_datetime.now(_v18_timezone.utc).isoformat(),
            "error": str(e),
            "summary": {
                "entry": 0,
                "manage_position": 0,
                "radar": 0,
                "wait_greeks": 0,
                "wait_data": 0,
                "blocked": 0,
                "total": 0,
            },
            "next_best_action": None,
            "recommendation": "No se pudo construir la decisión operativa.",
            "by_ticker": [],
            "by_strategy": [],
            "top": [],
            "health": {
                "snapshot_available": False,
                "rows_captured": 0,
                "can_operate_count": 0,
            },
        }

def v18_write_decision_snapshot(rows=None):
    try:
        payload = v18_build_decision_payload(rows or V17_SUMMARY_ROWS)
        V18_SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        V18_SNAPSHOT_PATH.write_text(_v18_json.dumps(payload, ensure_ascii=False, indent=2))
        return payload
    except Exception as e:
        return {
            "engine": "V18_OPERATIONAL_DECISION_API",
            "error": str(e),
            "recommendation": "No se pudo guardar el snapshot V18.",
        }
'''

if "V18 OPERATIONAL DECISION API HELPERS" not in s:
    marker = "# ============================================================\n# SUPER ENGINE BOLSA — V17.3C SUPPRESS IBKR NOISE"
    idx = s.find(marker)
    if idx != -1:
        s = s[:idx] + v18_block + "\n" + s[idx:]
    else:
        s = v18_block + "\n" + s

# ============================================================
# 3) Escribir snapshot V18 al final de cada ciclo
# ============================================================

old = 'print(v17_build_cycle_summary(locals()))'
new = '''print(v17_build_cycle_summary(locals()))
        try:
            v18_payload = v18_write_decision_snapshot(V17_SUMMARY_ROWS)
            nba = v18_payload.get("next_best_action")
            if nba:
                print("")
                print("V18 DECISION API SNAPSHOT UPDATED")
                print(f"NEXT: {nba.get('ticker')} | {nba.get('strategy')} | {nba.get('decision')} | can_operate:{nba.get('can_operate')}")
            else:
                print("")
                print("V18 DECISION API SNAPSHOT UPDATED | No next_best_action")
        except Exception as e:
            print(f"V18 snapshot error: {e}")'''

if "V18 DECISION API SNAPSHOT UPDATED" not in s:
    s = s.replace(old, new, 1)

bridge.write_text(s)

# ============================================================
# 4) Agregar endpoints a app/main.py
# ============================================================

m = main.read_text()

endpoint_block = r'''
# ============================================================
# SUPER ENGINE BOLSA — V18 OPERATIONAL DECISION API ENDPOINTS
# ============================================================

from pathlib import Path as _v18_api_Path
from datetime import datetime as _v18_api_datetime, timezone as _v18_api_timezone
import json as _v18_api_json

_V18_API_SNAPSHOT_PATHS = [
    _v18_api_Path("runtime/decision_desk_snapshot.json"),
    _v18_api_Path("../runtime/decision_desk_snapshot.json"),
    _v18_api_Path("/tmp/decision_desk_snapshot.json"),
]

def _v18_api_load_snapshot():
    for path in _V18_API_SNAPSHOT_PATHS:
        try:
            if path.exists():
                return _v18_api_json.loads(path.read_text())
        except Exception:
            pass

    return {
        "engine": "V18_OPERATIONAL_DECISION_API",
        "generated_at": _v18_api_datetime.now(_v18_api_timezone.utc).isoformat(),
        "snapshot_available": False,
        "summary": {
            "entry": 0,
            "manage_position": 0,
            "radar": 0,
            "wait_greeks": 0,
            "wait_data": 0,
            "blocked": 0,
            "total": 0,
        },
        "next_best_action": None,
        "recommendation": "No hay snapshot V18 disponible todavía. Corre ibkr_bridge.py para generar el último decision desk.",
        "by_ticker": [],
        "by_strategy": [],
        "top": [],
        "health": {
            "snapshot_available": False,
            "rows_captured": 0,
            "can_operate_count": 0,
        },
    }

@app.get("/decision_desk")
def decision_desk():
    return _v18_api_load_snapshot()

@app.get("/decision_desk/health")
def decision_desk_health():
    data = _v18_api_load_snapshot()
    return {
        "engine": "V18_OPERATIONAL_DECISION_API",
        "status": "OK" if data.get("health", {}).get("snapshot_available") else "NO_SNAPSHOT",
        "generated_at": data.get("generated_at"),
        "summary": data.get("summary"),
        "health": data.get("health"),
    }

@app.get("/decision_desk/{ticker}")
def decision_desk_ticker(ticker: str):
    data = _v18_api_load_snapshot()
    t = str(ticker or "").upper().strip()

    top = [
        row for row in data.get("top", [])
        if str(row.get("ticker", "")).upper() == t
    ]

    ticker_summary = None
    for item in data.get("by_ticker", []):
        if str(item.get("ticker", "")).upper() == t:
            ticker_summary = item
            break

    best = top[0] if top else None

    return {
        "engine": "V18_OPERATIONAL_DECISION_API",
        "ticker": t,
        "generated_at": data.get("generated_at"),
        "summary": ticker_summary or {
            "ticker": t,
            "total": 0,
            "entry": 0,
            "radar": 0,
            "wait_greeks": 0,
            "wait_data": 0,
            "blocked": 0,
            "best": None,
        },
        "next_best_action": best,
        "recommendation": best.get("recommendation") if best else f"No hay oportunidades capturadas para {t} en el último ciclo.",
        "top": top[:10],
    }
'''

if "V18 OPERATIONAL DECISION API ENDPOINTS" not in m:
    m = m.rstrip() + "\n\n" + endpoint_block + "\n"

main.write_text(m)
