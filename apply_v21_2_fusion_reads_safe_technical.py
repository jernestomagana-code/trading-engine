from pathlib import Path

p = Path("app/main.py")
s = p.read_text()

block = r'''
# ============================================================
# V21.2 — FUSION READS SAFE TECHNICAL SNAPSHOT STORE
# ============================================================

import json as _v212_json
from pathlib import Path as _v212_Path
from datetime import datetime as _v212_datetime, timezone as _v212_timezone

_V212_SAFE_TECH_FILE = _v212_Path("runtime") / "technical_snapshot_by_ticker_safe.json"
_V212_ALT_TECH_FILE = _v212_Path("runtime") / "technical_snapshot_by_ticker.json"

def _v212_now():
    return _v212_datetime.now(_v212_timezone.utc).isoformat()

def _v212_load_json(path):
    try:
        p = _v212_Path(path)
        if p.exists():
            txt = p.read_text()
            if txt.strip():
                data = _v212_json.loads(txt)
                if isinstance(data, dict):
                    return data
    except Exception:
        pass
    return {}

def _v212_get_safe_technical_by_ticker():
    data = {}

    # 1) Prioridad: memoria safe
    try:
        mem_safe = globals().get("TECHNICAL_SNAPSHOT_STORE_SAFE", {})
        if isinstance(mem_safe, dict):
            data.update(mem_safe)
    except Exception:
        pass

    # 2) Memoria standard
    try:
        mem_std = globals().get("TECHNICAL_SNAPSHOT_STORE", {})
        if isinstance(mem_std, dict):
            data.update(mem_std)
    except Exception:
        pass

    # 3) Archivo safe
    try:
        file_safe = _v212_load_json(_V212_SAFE_TECH_FILE)
        if isinstance(file_safe, dict):
            data.update(file_safe)
    except Exception:
        pass

    # 4) Archivo alternativo
    try:
        file_alt = _v212_load_json(_V212_ALT_TECH_FILE)
        if isinstance(file_alt, dict):
            data.update(file_alt)
    except Exception:
        pass

    # Limpieza de keys
    clean = {}
    for k, v in data.items():
        try:
            t = str(k or "").upper().strip()
            if t and isinstance(v, dict):
                clean[t] = v
        except Exception:
            pass

    return clean

def _v212_latest_technical_snapshot_store():
    by_ticker = _v212_get_safe_technical_by_ticker()
    return {
        "engine": "V21_2_FUSION_READS_SAFE_TECHNICAL",
        "available": bool(by_ticker),
        "technical_snapshot_available": bool(by_ticker),
        "updated_at": _v212_now(),
        "count": len(by_ticker),
        "tickers": sorted(list(by_ticker.keys())),
        "technical_tickers": sorted(list(by_ticker.keys())),
        "by_ticker": by_ticker,
        "source": "SAFE_TECHNICAL_SNAPSHOT_STORE",
        "path_safe": str(_V212_SAFE_TECH_FILE),
        "path_alt": str(_V212_ALT_TECH_FILE),
    }

# Sobrescribimos aliases usados por V21 fusion.
def get_latest_technical_snapshot():
    return _v212_latest_technical_snapshot_store()

def _get_latest_technical_snapshot():
    return _v212_latest_technical_snapshot_store()

def _load_technical_snapshot():
    return _v212_latest_technical_snapshot_store()

def get_technical_snapshot_store():
    return _v212_latest_technical_snapshot_store()

def _v212_get_technical_for_ticker(ticker):
    t = str(ticker or "").upper().strip()
    store = _v212_latest_technical_snapshot_store()
    return (store.get("by_ticker") or {}).get(t)

@app.get("/technical_snapshot_fusion_health")
def technical_snapshot_fusion_health():
    store = _v212_latest_technical_snapshot_store()
    return {
        "engine": "V21_2_FUSION_READS_SAFE_TECHNICAL",
        "status": "OK" if store.get("available") else "EMPTY",
        "technical_snapshot_available": store.get("technical_snapshot_available"),
        "technical_tickers": store.get("technical_tickers"),
        "count": store.get("count"),
        "source": store.get("source"),
        "path_safe": store.get("path_safe"),
        "path_alt": store.get("path_alt"),
    }

@app.get("/technical_snapshot_fusion/{ticker}")
def technical_snapshot_fusion_ticker(ticker: str):
    t = str(ticker or "").upper().strip()
    row = _v212_get_technical_for_ticker(t)
    return {
        "engine": "V21_2_FUSION_READS_SAFE_TECHNICAL",
        "ticker": t,
        "status": "OK" if row else "NO_TECHNICAL_SNAPSHOT_FOR_TICKER",
        "snapshot": row,
        "available_tickers": _v212_latest_technical_snapshot_store().get("technical_tickers", []),
    }
'''

if "V21.2 — FUSION READS SAFE TECHNICAL SNAPSHOT STORE" not in s:
    s = s.rstrip() + "\n\n" + block + "\n"

p.write_text(s)
