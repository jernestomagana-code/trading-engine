from pathlib import Path

main = Path("app/main.py")
m = main.read_text()

block = r'''
# ============================================================
# SUPER ENGINE BOLSA — V21.1 TECHNICAL SNAPSHOT INGEST + STORAGE
# ============================================================

import json as _v211_json
from pathlib import Path as _v211_Path
from datetime import datetime as _v211_datetime, timezone as _v211_timezone

_V211_RUNTIME_DIR = _v211_Path("runtime")
_V211_RUNTIME_DIR.mkdir(exist_ok=True)

_V211_TECHNICAL_SNAPSHOT_PATH = _V211_RUNTIME_DIR / "technical_snapshot.json"
_V211_TECHNICAL_BY_TICKER_PATH = _V211_RUNTIME_DIR / "technical_snapshot_by_ticker.json"

TECHNICAL_SNAPSHOT_STORE = globals().get("TECHNICAL_SNAPSHOT_STORE", {})
LATEST_TECHNICAL_SNAPSHOT = globals().get("LATEST_TECHNICAL_SNAPSHOT", {})

def _v211_now():
    return _v211_datetime.now(_v211_timezone.utc).isoformat()

def _v211_safe_float(value, default=None):
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default

def _v211_safe_bool(value, default=False):
    try:
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        s = str(value).strip().lower()
        if s in ["1", "true", "yes", "y", "si", "sí"]:
            return True
        if s in ["0", "false", "no", "n"]:
            return False
        return default
    except Exception:
        return default

def _v211_load_json_file(path, default):
    try:
        p = _v211_Path(path)
        if p.exists():
            raw = p.read_text()
            if raw.strip():
                return _v211_json.loads(raw)
    except Exception:
        pass
    return default

def _v211_write_json_file(path, payload):
    try:
        p = _v211_Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(_v211_json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        return True
    except Exception:
        return False

def _v211_normalize_technical_payload(payload):
    """
    Acepta payloads flexibles desde TradingView, curl, Make/Zapier o JSON manual.
    Devuelve lista normalizada de snapshots técnicos.
    """
    rows = []

    if payload is None:
        return rows

    # Si llega string JSON
    if isinstance(payload, str):
        try:
            payload = _v211_json.loads(payload)
        except Exception:
            payload = {"raw_message": payload}

    # Si llega lista
    if isinstance(payload, list):
        for item in payload:
            rows.extend(_v211_normalize_technical_payload(item))
        return rows

    if not isinstance(payload, dict):
        return rows

    # Si viene envuelto
    for key in ["technical_snapshot", "snapshot", "data", "payload"]:
        if isinstance(payload.get(key), dict):
            rows.extend(_v211_normalize_technical_payload(payload.get(key)))
            return rows

    for key in ["rows", "items", "snapshots", "tickers"]:
        if isinstance(payload.get(key), list):
            for item in payload.get(key):
                rows.extend(_v211_normalize_technical_payload(item))
            return rows

    ticker = (
        payload.get("ticker")
        or payload.get("symbol")
        or payload.get("syminfo.ticker")
        or payload.get("tv_ticker")
        or payload.get("asset")
    )

    if not ticker:
        # A veces TradingView manda ticker dentro de texto
        raw = str(payload.get("raw_message") or "")
        if raw:
            parts = raw.replace(",", " ").replace("|", " ").split()
            for p in parts:
                pp = p.strip().upper()
                if pp.isalpha() and 1 <= len(pp) <= 6:
                    ticker = pp
                    break

    if not ticker:
        return rows

    ticker = str(ticker).upper().strip()

    price = (
        payload.get("price")
        or payload.get("close")
        or payload.get("last")
        or payload.get("last_price")
    )

    trend = (
        payload.get("trend")
        or payload.get("trend_label")
        or payload.get("market_trend")
        or payload.get("bias")
    )

    score = (
        payload.get("score")
        or payload.get("technical_score")
        or payload.get("setup_score")
    )

    rsi = payload.get("rsi") or payload.get("RSI")
    macd = payload.get("macd") or payload.get("MACD")
    adx = payload.get("adx") or payload.get("ADX")
    vwap_position = payload.get("vwap_position") or payload.get("vwap")
    volume_relative = payload.get("volume_relative") or payload.get("relative_volume") or payload.get("rel_volume")
    support_near = payload.get("support_near") or payload.get("near_support")
    resistance_near = payload.get("resistance_near") or payload.get("near_resistance")
    range_breakout = payload.get("range_breakout") or payload.get("breakout")
    earnings_soon = payload.get("earnings_soon") or payload.get("earnings")
    event_risk = payload.get("event_risk")

    normalized = {
        "ticker": ticker,
        "received_at": _v211_now(),
        "source": payload.get("source") or "TRADINGVIEW_WEBHOOK_V21_1",
        "price": _v211_safe_float(price, price),
        "trend": trend,
        "score": _v211_safe_float(score, score),
        "rsi": _v211_safe_float(rsi, rsi),
        "macd": _v211_safe_float(macd, macd),
        "adx": _v211_safe_float(adx, adx),
        "vwap_position": vwap_position,
        "volume_relative": _v211_safe_float(volume_relative, volume_relative),
        "support_near": _v211_safe_bool(support_near, False),
        "resistance_near": _v211_safe_bool(resistance_near, False),
        "range_breakout": _v211_safe_bool(range_breakout, False),
        "earnings_soon": _v211_safe_bool(earnings_soon, False),
        "event_risk": _v211_safe_bool(event_risk, False),
        "raw": payload,
    }

    # Clasificación flexible si TradingView manda action/señal
    signal = str(payload.get("signal") or payload.get("action") or "").upper()
    if signal and not normalized.get("trend"):
        if "BUY" in signal or "LONG" in signal or "BULL" in signal:
            normalized["trend"] = "BULLISH"
        elif "SELL" in signal or "SHORT" in signal or "BEAR" in signal:
            normalized["trend"] = "BEARISH"
        elif "NEUTRAL" in signal or "RANGE" in signal:
            normalized["trend"] = "NEUTRAL"

    rows.append(normalized)
    return rows

def _v211_load_technical_by_ticker():
    by_ticker = {}

    try:
        if isinstance(globals().get("TECHNICAL_SNAPSHOT_STORE"), dict):
            by_ticker.update(globals().get("TECHNICAL_SNAPSHOT_STORE") or {})
    except Exception:
        pass

    file_data = _v211_load_json_file(_V211_TECHNICAL_BY_TICKER_PATH, {})
    if isinstance(file_data, dict):
        by_ticker.update(file_data)

    return by_ticker

def _v211_save_technical_snapshots(rows):
    global TECHNICAL_SNAPSHOT_STORE
    global LATEST_TECHNICAL_SNAPSHOT

    by_ticker = _v211_load_technical_by_ticker()

    for row in rows:
        t = str(row.get("ticker") or "").upper().strip()
        if not t:
            continue
        by_ticker[t] = row
        LATEST_TECHNICAL_SNAPSHOT = row

    TECHNICAL_SNAPSHOT_STORE = by_ticker

    payload = {
        "engine": "V21_1_TECHNICAL_SNAPSHOT_INGEST",
        "updated_at": _v211_now(),
        "count": len(by_ticker),
        "tickers": sorted(list(by_ticker.keys())),
        "by_ticker": by_ticker,
    }

    _v211_write_json_file(_V211_TECHNICAL_BY_TICKER_PATH, by_ticker)
    _v211_write_json_file(_V211_TECHNICAL_SNAPSHOT_PATH, payload)

    return payload

def _v211_get_technical_snapshot_store():
    by_ticker = _v211_load_technical_by_ticker()
    return {
        "engine": "V21_1_TECHNICAL_SNAPSHOT_INGEST",
        "available": bool(by_ticker),
        "updated_at": _v211_now(),
        "count": len(by_ticker),
        "tickers": sorted(list(by_ticker.keys())),
        "by_ticker": by_ticker,
    }

# Alias que V21 puede intentar encontrar
def get_latest_technical_snapshot():
    return _v211_get_technical_snapshot_store()

def _load_technical_snapshot():
    return _v211_get_technical_snapshot_store()

def _get_latest_technical_snapshot():
    return _v211_get_technical_snapshot_store()

@app.post("/technical_snapshot")
async def technical_snapshot_ingest(request: Request):
    try:
        payload = await request.json()
    except Exception:
        try:
            raw = await request.body()
            payload = raw.decode("utf-8")
        except Exception:
            payload = {}

    rows = _v211_normalize_technical_payload(payload)
    saved = _v211_save_technical_snapshots(rows)

    return {
        "engine": "V21_1_TECHNICAL_SNAPSHOT_INGEST",
        "status": "OK" if rows else "NO_VALID_TECHNICAL_ROWS",
        "received_rows": len(rows),
        "stored_tickers": saved.get("tickers", []),
        "stored_count": saved.get("count", 0),
        "updated_at": saved.get("updated_at"),
    }

@app.post("/webhook/technical_snapshot")
async def technical_snapshot_webhook(request: Request):
    return await technical_snapshot_ingest(request)

@app.post("/webhook/tradingview_technical")
async def tradingview_technical_webhook(request: Request):
    return await technical_snapshot_ingest(request)

@app.get("/technical_snapshot")
def technical_snapshot_get():
    return _v211_get_technical_snapshot_store()

@app.get("/technical_snapshot/{ticker}")
def technical_snapshot_ticker(ticker: str):
    data = _v211_get_technical_snapshot_store()
    t = str(ticker or "").upper().strip()
    row = (data.get("by_ticker") or {}).get(t)
    return {
        "engine": "V21_1_TECHNICAL_SNAPSHOT_INGEST",
        "ticker": t,
        "status": "OK" if row else "NO_TECHNICAL_SNAPSHOT_FOR_TICKER",
        "snapshot": row,
        "available_tickers": data.get("tickers", []),
    }

@app.get("/technical_snapshot_health")
def technical_snapshot_health():
    data = _v211_get_technical_snapshot_store()
    return {
        "engine": "V21_1_TECHNICAL_SNAPSHOT_INGEST",
        "status": "OK" if data.get("available") else "EMPTY",
        "available": data.get("available"),
        "count": data.get("count"),
        "tickers": data.get("tickers"),
        "path_by_ticker": str(_V211_TECHNICAL_BY_TICKER_PATH),
        "path_snapshot": str(_V211_TECHNICAL_SNAPSHOT_PATH),
    }
'''

if "V21.1 TECHNICAL SNAPSHOT INGEST + STORAGE" not in m:
    m = m.rstrip() + "\n\n" + block + "\n"

main.write_text(m)
