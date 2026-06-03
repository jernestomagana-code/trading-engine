from pathlib import Path

p = Path("app/main.py")
s = p.read_text()

backup = Path("app/main_backup_before_v22_1_snapshot_normalizer.py")
backup.write_text(s)

marker = "# === V22.1 SNAPSHOT NORMALIZER + UNIFIED DECISION READER ==="

block = r'''
# === V22.1 SNAPSHOT NORMALIZER + UNIFIED DECISION READER ===

from pathlib import Path as _V22Path
import json as _v22_json
from datetime import datetime as _v22_dt
from zoneinfo import ZoneInfo as _V22ZoneInfo

V22_1_ENGINE = "V22_1_SNAPSHOT_NORMALIZER"

V22_TECH_FILES = [
    "runtime/technical_snapshot_by_ticker_safe.json",
    "runtime/technical_snapshot_by_ticker.json",
    "technical_snapshot_by_ticker_safe.json",
    "technical_snapshot_by_ticker.json",
]

V22_DECISION_FILES = [
    "runtime/decision_desk_snapshot.json",
    "runtime/decision_snapshot.json",
    "runtime/v18_decision_snapshot.json",
    "runtime/v18_decision_desk_snapshot.json",
    "decision_desk_snapshot.json",
    "decision_snapshot.json",
]


def _v22_safe_load_json(path: str):
    try:
        fp = _V22Path(path)
        if not fp.exists():
            return None
        raw = fp.read_text().strip()
        if not raw:
            return None
        return _v22_json.loads(raw)
    except Exception:
        return None


def _v22_find_first_json(paths):
    for path in paths:
        data = _v22_safe_load_json(path)
        if data is not None:
            return path, data
    return None, None


def _v22_normalize_ticker(ticker: str):
    return str(ticker or "").strip().upper()


def _v22_extract_snapshot_payload(obj):
    """
    Acepta estructuras como:
    {"QQQ": {"trend": "BULLISH"}}
    {"QQQ": {"snapshot": {"trend": "BULLISH"}}}
    {"ticker": "QQQ", "snapshot": {...}}
    {"snapshot": {"ticker": "QQQ", ...}}
    """
    if not isinstance(obj, dict):
        return {}

    if isinstance(obj.get("snapshot"), dict):
        snap = obj.get("snapshot")
        merged = dict(obj)
        merged.update(snap)
        return merged

    if isinstance(obj.get("raw"), dict):
        raw = obj.get("raw")
        merged = dict(obj)
        merged.update(raw)
        return merged

    return obj


def _v22_get_technical_snapshot(ticker: str):
    ticker = _v22_normalize_ticker(ticker)
    path, data = _v22_find_first_json(V22_TECH_FILES)

    out = {
        "available": False,
        "path": path,
        "available_tickers": [],
        "ticker": ticker,
        "snapshot": None,
        "bias": "UNKNOWN",
        "score": None,
        "trend": "UNKNOWN",
        "reason": "No technical snapshot available",
    }

    if data is None:
        return out

    if isinstance(data, dict):
        out["available_tickers"] = list(data.keys())

        candidate = None

        if ticker in data:
            candidate = data.get(ticker)
        elif data.get("ticker") == ticker:
            candidate = data
        elif isinstance(data.get("snapshot"), dict) and data.get("snapshot", {}).get("ticker") == ticker:
            candidate = data.get("snapshot")

        if candidate is None:
            # fallback: buscar por ticker interno en valores
            for k, v in data.items():
                if isinstance(v, dict):
                    payload = _v22_extract_snapshot_payload(v)
                    if _v22_normalize_ticker(payload.get("ticker") or k) == ticker:
                        candidate = v
                        break

        if candidate is not None:
            payload = _v22_extract_snapshot_payload(candidate)
            trend = str(payload.get("trend") or payload.get("bias") or payload.get("technical_bias") or "UNKNOWN").upper()
            score = payload.get("score", payload.get("technical_score", payload.get("confidence")))

            bias = trend
            if trend in ["BULL", "BULLISH", "ALCISTA", "UP"]:
                bias = "BULLISH"
            elif trend in ["BEAR", "BEARISH", "BAJISTA", "DOWN"]:
                bias = "BEARISH"
            elif trend in ["NEUTRAL", "SIDEWAYS", "RANGE", "LATERAL"]:
                bias = "NEUTRAL"

            out.update({
                "available": True,
                "snapshot": payload,
                "bias": bias,
                "trend": trend,
                "score": score,
                "reason": "Technical snapshot loaded",
            })
            return out

    return out


def _v22_extract_rows_from_decision_snapshot(data):
    if data is None:
        return []

    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]

    if isinstance(data, dict):
        for key in ["rows", "top", "top_5", "opportunities", "items", "data"]:
            val = data.get(key)
            if isinstance(val, list):
                return [x for x in val if isinstance(x, dict)]

        summary = data.get("summary")
        if isinstance(summary, dict):
            for key in ["top", "top_5", "rows", "opportunities", "items"]:
                val = summary.get(key)
                if isinstance(val, list):
                    return [x for x in val if isinstance(x, dict)]

        by_ticker = data.get("by_ticker")
        if isinstance(by_ticker, dict):
            rows = []
            for tk, payload in by_ticker.items():
                if isinstance(payload, dict):
                    best = payload.get("best")
                    if isinstance(best, dict):
                        best = dict(best)
                        best.setdefault("ticker", tk)
                        rows.append(best)
                    nested = payload.get("rows")
                    if isinstance(nested, list):
                        for r in nested:
                            if isinstance(r, dict):
                                rr = dict(r)
                                rr.setdefault("ticker", tk)
                                rows.append(rr)
            return rows

    return []


def _v22_get_decision_snapshot():
    path, data = _v22_find_first_json(V22_DECISION_FILES)
    rows = _v22_extract_rows_from_decision_snapshot(data)
    return {
        "available": data is not None,
        "path": path,
        "raw": data,
        "rows": rows,
        "rows_found": len(rows),
    }


def _v22_market_hours_state():
    try:
        now = _v22_dt.now(_V22ZoneInfo("America/New_York"))
        weekday = now.weekday()
        minutes = now.hour * 60 + now.minute

        if weekday >= 5:
            return {
                "status": "WEEKEND_CLOSED",
                "label": "Mercado cerrado por fin de semana",
                "is_regular_market_open": False,
                "options_bidask_expected": False,
                "new_york_time": now.isoformat(),
                "next_check": "Próxima sesión hábil después de 09:35 ET.",
            }

        regular_open = 9 * 60 + 30
        reliable_options = 9 * 60 + 35
        regular_close = 16 * 60

        if minutes < regular_open:
            return {
                "status": "PRE_MARKET",
                "label": "Pre-market: opciones todavía no confiables",
                "is_regular_market_open": False,
                "options_bidask_expected": False,
                "new_york_time": now.isoformat(),
                "next_check": "Revisar después de 09:35 ET.",
            }

        if regular_open <= minutes < reliable_options:
            return {
                "status": "MARKET_OPEN_NOT_LIQUID_YET",
                "label": "Mercado recién abierto: esperar bid/ask confiable",
                "is_regular_market_open": True,
                "options_bidask_expected": False,
                "new_york_time": now.isoformat(),
                "next_check": "Revisar después de 09:35 ET.",
            }

        if reliable_options <= minutes < regular_close:
            return {
                "status": "REGULAR_MARKET_OPEN",
                "label": "Mercado regular abierto",
                "is_regular_market_open": True,
                "options_bidask_expected": True,
                "new_york_time": now.isoformat(),
                "next_check": "Monitoreo activo.",
            }

        return {
            "status": "AFTER_HOURS",
            "label": "After-hours: opciones no confiables",
            "is_regular_market_open": False,
            "options_bidask_expected": False,
            "new_york_time": now.isoformat(),
            "next_check": "Revisar próxima sesión después de 09:35 ET.",
        }
    except Exception as e:
        return {
            "status": "UNKNOWN",
            "label": f"Market hours unavailable: {e}",
            "is_regular_market_open": False,
            "options_bidask_expected": False,
            "new_york_time": None,
            "next_check": "Validar horario manualmente.",
        }


def _v22_score_row(row):
    try:
        return float(row.get("combined_score", row.get("score", row.get("master_score", 0))) or 0)
    except Exception:
        return 0.0


def _v22_row_ticker(row):
    return _v22_normalize_ticker(row.get("ticker") or row.get("symbol") or row.get("underlying") or row.get("underlying_symbol"))


def _v22_row_strategy(row):
    return str(row.get("strategy") or row.get("strategy_hint") or row.get("option_type") or row.get("setup") or "UNKNOWN").upper()


def _v22_rows_for_ticker(rows, ticker):
    ticker = _v22_normalize_ticker(ticker)
    return [r for r in rows if _v22_row_ticker(r) == ticker]


def _v22_best_row(rows):
    if not rows:
        return None
    return sorted(rows, key=_v22_score_row, reverse=True)[0]


def _v22_unified_decision(ticker: str):
    ticker = _v22_normalize_ticker(ticker)
    tech = _v22_get_technical_snapshot(ticker)
    decision = _v22_get_decision_snapshot()
    market = _v22_market_hours_state()

    rows = _v22_rows_for_ticker(decision["rows"], ticker)
    best = _v22_best_row(rows)

    technical_bias = tech.get("bias", "UNKNOWN")
    technical_score = tech.get("score")
    options_rows_found = len(rows)
    decision_snapshot_available = decision.get("available", False)
    technical_snapshot_available = tech.get("available", False)

    final_state = "NO_DATA"
    main_blocker = None
    can_operate = False
    severity = "gray"
    action = "No operar. Faltan datos suficientes."
    decision_label = "NO_DATA"

    if not market.get("options_bidask_expected"):
        final_state = "WAIT_MARKET_OPEN"
        decision_label = "WAIT_MARKET_OPEN"
        main_blocker = "OPTIONS_MARKET_NOT_RELIABLE"
        severity = "gray"
        action = f"No operar ahora. Esperar ventana confiable de mercado/opciones. {market.get('next_check')}"
    elif not technical_snapshot_available and not decision_snapshot_available:
        final_state = "NO_SNAPSHOTS"
        decision_label = "WAIT_DATA"
        main_blocker = "NO_TECHNICAL_OR_OPTIONS_SNAPSHOT"
        severity = "red"
        action = "No operar. Falta snapshot técnico y snapshot de opciones."
    elif not technical_snapshot_available:
        final_state = "WAIT_TECHNICAL"
        decision_label = "WAIT_DATA"
        main_blocker = "NO_TECHNICAL_SNAPSHOT"
        severity = "orange"
        action = "No operar. Falta confirmación técnica."
    elif not decision_snapshot_available or options_rows_found == 0:
        final_state = "WAIT_OPTIONS"
        decision_label = "WAIT_DATA"
        main_blocker = "NO_OPTIONS_DECISION_ROWS"
        severity = "orange"
        action = "No operar. Falta snapshot de opciones/decision desk."
    else:
        best_strategy = _v22_row_strategy(best)
        best_score = _v22_score_row(best)

        strategy_is_bullish = best_strategy in ["NAKED_PUT", "PUT", "BULL_PUT", "BULL_PUT_SPREAD", "CSP"]
        strategy_is_bearish = best_strategy in ["COVERED_CALL", "CALL", "BEAR_CALL", "BEAR_CALL_SPREAD"]

        technical_supports_strategy = (
            technical_bias == "BULLISH" and strategy_is_bullish
        ) or (
            technical_bias == "BEARISH" and strategy_is_bearish
        ) or (
            technical_bias == "NEUTRAL"
        )

        if technical_bias == "UNKNOWN":
            final_state = "RADAR_TECH_UNKNOWN"
            decision_label = "RADAR"
            main_blocker = "TECHNICAL_BIAS_UNKNOWN"
            severity = "orange"
            action = "Mantener en radar. Falta interpretar sesgo técnico con claridad."
        elif not technical_supports_strategy:
            final_state = "TECHNICAL_CONFLICT"
            decision_label = "WAIT_DATA"
            main_blocker = "TECHNICAL_STRATEGY_CONFLICT"
            severity = "red"
            action = f"No operar. Sesgo técnico {technical_bias} no confirma estrategia {best_strategy}."
        elif best_score >= 85:
            final_state = "ENTRY_CONFIRMED"
            decision_label = "ENTRY_CONFIRMED"
            can_operate = True
            severity = "green"
            action = f"Entrada candidata confirmada: {ticker} / {best_strategy}. Validar manualmente spread, liquidez, tamaño y riesgo antes de operar."
        elif best_score >= 60:
            final_state = "RADAR_TECH_OK"
            decision_label = "RADAR"
            severity = "orange"
            action = f"Mantener en radar: {ticker} / {best_strategy}. Técnica acompaña, pero score todavía no confirma entrada."
        else:
            final_state = "LOW_PRIORITY"
            decision_label = "LOW_PRIORITY"
            severity = "gray"
            action = "No operar. Oportunidad de baja prioridad."

    return {
        "engine": V22_1_ENGINE,
        "generated_at": _v22_dt.utcnow().isoformat() + "+00:00",
        "ticker": ticker,
        "status": "OK",
        "final_state": final_state,
        "decision": decision_label,
        "can_operate": can_operate,
        "severity": severity,
        "main_blocker": main_blocker,
        "action": action,
        "executive_summary": f"{ticker}: estado {final_state}. Sesgo técnico {technical_bias}. {action}",
        "technical": {
            "available": technical_snapshot_available,
            "path": tech.get("path"),
            "bias": technical_bias,
            "trend": tech.get("trend"),
            "score": technical_score,
            "available_tickers": tech.get("available_tickers", []),
            "snapshot": tech.get("snapshot"),
        },
        "options": {
            "available": decision_snapshot_available,
            "path": decision.get("path"),
            "rows_found_for_ticker": options_rows_found,
            "total_rows_found": decision.get("rows_found", 0),
            "best": best,
            "rows": rows[:25],
        },
        "market_hours": market,
        "diagnostics": {
            "technical_snapshot_available": technical_snapshot_available,
            "decision_snapshot_available": decision_snapshot_available,
            "options_rows_found": options_rows_found,
            "safe_technical_files": V22_TECH_FILES,
            "decision_files": V22_DECISION_FILES,
        },
    }


@app.get("/v22_1_trade_decision/{ticker}")
def v22_1_trade_decision(ticker: str):
    return _v22_unified_decision(ticker)


@app.get("/v22_1_system_status")
def v22_1_system_status():
    tech_path, tech_data = _v22_find_first_json(V22_TECH_FILES)
    dec = _v22_get_decision_snapshot()
    market = _v22_market_hours_state()

    technical_tickers = []
    if isinstance(tech_data, dict):
        technical_tickers = list(tech_data.keys())

    return {
        "engine": V22_1_ENGINE,
        "status": "OK",
        "generated_at": _v22_dt.utcnow().isoformat() + "+00:00",
        "technical_snapshot_available": tech_data is not None,
        "technical_snapshot_path": tech_path,
        "technical_tickers": technical_tickers,
        "decision_snapshot_available": dec.get("available"),
        "decision_snapshot_path": dec.get("path"),
        "decision_rows_found": dec.get("rows_found"),
        "market_hours": market,
        "endpoints": {
            "v22_1_trade_decision_example": "/v22_1_trade_decision/QQQ",
            "v22_1_system_status": "/v22_1_system_status",
        },
    }
# === END V22.1 SNAPSHOT NORMALIZER + UNIFIED DECISION READER ===
'''

if marker not in s:
    s = s.rstrip() + "\n\n" + block + "\n"
else:
    print("V22.1 block already present; no duplicate inserted.")

p.write_text(s)
print("V22.1 Snapshot Normalizer installed.")
