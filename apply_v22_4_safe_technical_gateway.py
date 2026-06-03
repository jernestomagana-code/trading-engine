from pathlib import Path
import re

MAIN = Path("app/main.py")
s = MAIN.read_text()

backup = Path("app/main_backup_before_v22_4_safe_technical_gateway.py")
backup.write_text(s)

marker = "# === V22.4 SAFE TECHNICAL SNAPSHOT GATEWAY ==="

# Evitar duplicar el bloque si ya existe
if marker not in s:
    block = r'''

# === V22.4 SAFE TECHNICAL SNAPSHOT GATEWAY ===
from pathlib import Path as _V224Path
from datetime import datetime as _V224DateTime, timezone as _V224Timezone
import json as _v224_json

_V224_RUNTIME_DIR = _V224Path("runtime")
_V224_RUNTIME_DIR.mkdir(exist_ok=True)

_V224_SAFE_TECH_FILE = _V224_RUNTIME_DIR / "technical_snapshot_by_ticker_safe.json"


def _v224_utc_now():
    return _V224DateTime.now(_V224Timezone.utc).isoformat()


def _v224_load_safe_technical_store():
    try:
        if not _V224_SAFE_TECH_FILE.exists():
            return {}
        raw = _V224_SAFE_TECH_FILE.read_text()
        if not raw.strip():
            return {}
        data = _v224_json.loads(raw)
        if isinstance(data, dict):
            return data
        return {}
    except Exception:
        return {}


def _v224_save_safe_technical_store(store: dict):
    try:
        _V224_SAFE_TECH_FILE.parent.mkdir(exist_ok=True)
        _V224_SAFE_TECH_FILE.write_text(
            _v224_json.dumps(store, indent=2, ensure_ascii=False)
        )
        return True
    except Exception:
        return False


def _v224_normalize_technical_payload(payload: dict):
    if not isinstance(payload, dict):
        payload = {}

    ticker = str(payload.get("ticker") or "").upper().strip()
    if not ticker:
        ticker = "UNKNOWN"

    def _num(x, default=None):
        try:
            if x is None or x == "":
                return default
            return float(x)
        except Exception:
            return default

    trend = str(payload.get("trend") or payload.get("bias") or "UNKNOWN").upper().strip()

    snapshot = {
        "ticker": ticker,
        "received_at": _v224_utc_now(),
        "source": payload.get("source") or "TECHNICAL_SNAPSHOT_SAFE_V22_4",
        "price": _num(payload.get("price")),
        "trend": trend,
        "score": _num(payload.get("score")),
        "rsi": _num(payload.get("rsi")),
        "adx": _num(payload.get("adx")),
        "macd": payload.get("macd"),
        "vwap_position": payload.get("vwap_position"),
        "volume_relative": _num(payload.get("volume_relative")),
        "support_near": bool(payload.get("support_near", False)),
        "resistance_near": bool(payload.get("resistance_near", False)),
        "range_breakout": bool(payload.get("range_breakout", False)),
        "event_risk": bool(payload.get("event_risk", False)),
        "raw": payload,
    }

    return ticker, snapshot


@app.post("/technical_snapshot_safe")
async def v224_post_technical_snapshot_safe(payload: dict):
    try:
        ticker, snapshot = _v224_normalize_technical_payload(payload)
        store = _v224_load_safe_technical_store()
        store[ticker] = snapshot
        ok = _v224_save_safe_technical_store(store)

        return {
            "engine": "V22_4_SAFE_TECHNICAL_GATEWAY",
            "status": "OK" if ok else "SAVE_FAILED",
            "ticker": ticker,
            "snapshot": snapshot,
            "available_tickers": sorted(list(store.keys())),
            "path": str(_V224_SAFE_TECH_FILE),
        }
    except Exception as e:
        return {
            "engine": "V22_4_SAFE_TECHNICAL_GATEWAY",
            "status": "ERROR_HANDLED",
            "error": str(e),
            "payload_preview": str(payload)[:500],
        }


@app.get("/technical_snapshot_safe_status")
async def v224_get_technical_snapshot_safe_status():
    store = _v224_load_safe_technical_store()
    return {
        "engine": "V22_4_SAFE_TECHNICAL_GATEWAY",
        "status": "OK",
        "technical_snapshot_available": bool(store),
        "technical_tickers": sorted(list(store.keys())),
        "count": len(store),
        "path": str(_V224_SAFE_TECH_FILE),
    }


@app.get("/technical_snapshot_safe/{ticker}")
async def v224_get_technical_snapshot_safe_ticker(ticker: str):
    store = _v224_load_safe_technical_store()
    t = str(ticker or "").upper().strip()
    snap = store.get(t)

    return {
        "engine": "V22_4_SAFE_TECHNICAL_GATEWAY",
        "ticker": t,
        "status": "OK" if snap else "NO_TECHNICAL_SNAPSHOT_FOR_TICKER",
        "snapshot": snap,
        "available_tickers": sorted(list(store.keys())),
    }

# === END V22.4 SAFE TECHNICAL SNAPSHOT GATEWAY ===
'''

    s = s.rstrip() + "\n\n" + block + "\n"
    MAIN.write_text(s)
    print("V22.4 safe technical gateway added to app/main.py")
else:
    print("V22.4 safe technical gateway already exists. No duplicate inserted.")
