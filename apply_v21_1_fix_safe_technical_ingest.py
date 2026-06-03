from pathlib import Path

p = Path("app/main.py")
s = p.read_text()

block = r'''
# ============================================================
# V21.1 FIX — SAFE TECHNICAL SNAPSHOT INGEST
# ============================================================

import json as _v211f_json
from pathlib import Path as _v211f_Path
from datetime import datetime as _v211f_datetime, timezone as _v211f_timezone

_V211F_RUNTIME = _v211f_Path("runtime")
_V211F_RUNTIME.mkdir(exist_ok=True)
_V211F_FILE = _V211F_RUNTIME / "technical_snapshot_by_ticker_safe.json"

TECHNICAL_SNAPSHOT_STORE_SAFE = globals().get("TECHNICAL_SNAPSHOT_STORE_SAFE", {})

def _v211f_now():
    return _v211f_datetime.now(_v211f_timezone.utc).isoformat()

def _v211f_load():
    try:
        if _V211F_FILE.exists():
            txt = _V211F_FILE.read_text()
            if txt.strip():
                data = _v211f_json.loads(txt)
                if isinstance(data, dict):
                    return data
    except Exception:
        pass
    return {}

def _v211f_save(data):
    try:
        _V211F_FILE.parent.mkdir(parents=True, exist_ok=True)
        _V211F_FILE.write_text(_v211f_json.dumps(data, ensure_ascii=False, indent=2, default=str))
        return True
    except Exception:
        return False

def _v211f_float(x, default=None):
    try:
        if x is None or x == "":
            return default
        return float(x)
    except Exception:
        return default

def _v211f_bool(x, default=False):
    if isinstance(x, bool):
        return x
    if x is None:
        return default
    v = str(x).strip().lower()
    if v in ["true", "1", "yes", "y", "si", "sí"]:
        return True
    if v in ["false", "0", "no", "n"]:
        return False
    return default

def _v211f_normalize_one(payload):
    if not isinstance(payload, dict):
        return None

    ticker = payload.get("ticker") or payload.get("symbol") or payload.get("asset")
    if not ticker:
        return None

    ticker = str(ticker).upper().strip()

    trend = payload.get("trend") or payload.get("bias") or payload.get("signal") or "UNKNOWN"
    trend = str(trend).upper().strip()

    row = {
        "ticker": ticker,
        "received_at": _v211f_now(),
        "source": payload.get("source") or "TECHNICAL_SNAPSHOT_SAFE_INGEST",
        "price": _v211f_float(payload.get("price") or payload.get("close") or payload.get("last")),
        "trend": trend,
        "score": _v211f_float(payload.get("score") or payload.get("technical_score"), 0),
        "rsi": _v211f_float(payload.get("rsi")),
        "adx": _v211f_float(payload.get("adx")),
        "macd": payload.get("macd"),
        "vwap_position": payload.get("vwap_position") or payload.get("vwap"),
        "volume_relative": _v211f_float(payload.get("volume_relative") or payload.get("relative_volume")),
        "support_near": _v211f_bool(payload.get("support_near")),
        "resistance_near": _v211f_bool(payload.get("resistance_near")),
        "range_breakout": _v211f_bool(payload.get("range_breakout")),
        "event_risk": _v211f_bool(payload.get("event_risk")),
        "raw": payload,
    }

    return row

def _v211f_extract_rows(payload):
    if isinstance(payload, list):
        out = []
        for item in payload:
            row = _v211f_normalize_one(item)
            if row:
                out.append(row)
        return out

    if isinstance(payload, dict):
        for k in ["rows", "items", "tickers", "snapshots"]:
            if isinstance(payload.get(k), list):
                return _v211f_extract_rows(payload.get(k))

        row = _v211f_normalize_one(payload)
        return [row] if row else []

    return []

def _v211f_get_store():
    data = _v211f_load()
    mem = globals().get("TECHNICAL_SNAPSHOT_STORE_SAFE", {})
    if isinstance(mem, dict):
        data.update(mem)

    return {
        "engine": "V21_1_FIX_SAFE_TECHNICAL_INGEST",
        "available": bool(data),
        "count": len(data),
        "tickers": sorted(list(data.keys())),
        "by_ticker": data,
        "path": str(_V211F_FILE),
        "updated_at": _v211f_now(),
    }

# Estos aliases ayudan a que V21 pueda detectar el snapshot técnico.
def get_latest_technical_snapshot_safe():
    return _v211f_get_store()

def get_latest_technical_snapshot():
    return _v211f_get_store()

def _get_latest_technical_snapshot():
    return _v211f_get_store()

def _load_technical_snapshot():
    return _v211f_get_store()

@app.post("/technical_snapshot_ingest")
async def technical_snapshot_ingest_safe(request: Request):
    try:
        payload = await request.json()
    except Exception as e:
        return {
            "engine": "V21_1_FIX_SAFE_TECHNICAL_INGEST",
            "status": "BAD_JSON",
            "error": str(e),
        }

    rows = _v211f_extract_rows(payload)

    store = _v211f_load()

    for row in rows:
        ticker = row.get("ticker")
        if ticker:
            store[ticker] = row

    globals()["TECHNICAL_SNAPSHOT_STORE_SAFE"] = store
    globals()["TECHNICAL_SNAPSHOT_STORE"] = store
    globals()["LATEST_TECHNICAL_SNAPSHOT"] = rows[-1] if rows else {}

    saved = _v211f_save(store)

    return {
        "engine": "V21_1_FIX_SAFE_TECHNICAL_INGEST",
        "status": "OK" if rows else "NO_VALID_ROWS",
        "received_rows": len(rows),
        "stored_count": len(store),
        "stored_tickers": sorted(list(store.keys())),
        "saved_to_file": saved,
        "path": str(_V211F_FILE),
    }

@app.get("/technical_snapshot_safe")
def technical_snapshot_safe_get():
    return _v211f_get_store()

@app.get("/technical_snapshot_safe/{ticker}")
def technical_snapshot_safe_ticker(ticker: str):
    data = _v211f_get_store()
    t = str(ticker or "").upper().strip()
    row = (data.get("by_ticker") or {}).get(t)
    return {
        "engine": "V21_1_FIX_SAFE_TECHNICAL_INGEST",
        "ticker": t,
        "status": "OK" if row else "NO_TECHNICAL_SNAPSHOT_FOR_TICKER",
        "snapshot": row,
        "available_tickers": data.get("tickers", []),
    }
'''

if "V21.1 FIX — SAFE TECHNICAL SNAPSHOT INGEST" not in s:
    s = s.rstrip() + "\n\n" + block + "\n"

p.write_text(s)
