from pathlib import Path
import re

APP = Path("app/main.py")
BRIDGE = Path("ibkr_bridge.py")

app = APP.read_text()
bridge = BRIDGE.read_text()

APP.write_text(app + "\n")
BRIDGE.write_text(bridge + "\n")

app = APP.read_text()
bridge = BRIDGE.read_text()

# ============================================================
# V22.2 APP MAIN PATCH — REMOTE SNAPSHOT SYNC ENDPOINTS
# ============================================================

v22_2_app_block = r'''
# ============================================================
# V22.2 REMOTE SNAPSHOT SYNC — SERVER INGEST + STORE
# ============================================================

import json as _v22_2_json
from pathlib import Path as _v22_2_Path
from datetime import datetime as _v22_2_datetime, timezone as _v22_2_timezone

_V22_2_RUNTIME_DIR = _v22_2_Path("runtime")
_V22_2_RUNTIME_DIR.mkdir(exist_ok=True)

_V22_2_TECH_FILE = _V22_2_RUNTIME_DIR / "technical_snapshot_by_ticker_safe.json"
_V22_2_DECISION_FILE = _V22_2_RUNTIME_DIR / "decision_desk_snapshot.json"
_V22_2_UNIFIED_FILE = _V22_2_RUNTIME_DIR / "v22_2_unified_remote_snapshot.json"

def _v22_2_now_iso():
    return _v22_2_datetime.now(_v22_2_timezone.utc).isoformat()

def _v22_2_safe_read_json(path, default):
    try:
        if path.exists():
            return _v22_2_json.loads(path.read_text())
    except Exception:
        pass
    return default

def _v22_2_safe_write_json(path, payload):
    try:
        path.parent.mkdir(exist_ok=True)
        path.write_text(_v22_2_json.dumps(payload, ensure_ascii=False, indent=2))
        return True
    except Exception:
        return False

def _v22_2_extract_ticker(payload):
    try:
        ticker = payload.get("ticker")
        if not ticker and isinstance(payload.get("snapshot"), dict):
            ticker = payload["snapshot"].get("ticker")
        if not ticker and isinstance(payload.get("technical"), dict):
            ticker = payload["technical"].get("ticker")
        return str(ticker or "").upper().strip()
    except Exception:
        return ""

def _v22_2_normalize_technical_payload(payload):
    ticker = _v22_2_extract_ticker(payload)
    if not ticker:
        ticker = "UNKNOWN"

    snapshot = payload.get("snapshot") if isinstance(payload.get("snapshot"), dict) else payload
    if isinstance(payload.get("technical"), dict):
        snapshot = payload.get("technical")

    snapshot = dict(snapshot or {})
    snapshot["ticker"] = str(snapshot.get("ticker") or ticker).upper()
    snapshot["received_at"] = _v22_2_now_iso()
    snapshot["source"] = snapshot.get("source") or payload.get("source") or "REMOTE_V22_2"

    return ticker, snapshot

def _v22_2_normalize_decision_payload(payload):
    data = dict(payload or {})
    data["received_at"] = _v22_2_now_iso()
    data["source"] = data.get("source") or "REMOTE_V22_2"
    return data

@app.post("/v22_2_ingest_technical_snapshot")
def v22_2_ingest_technical_snapshot(payload: dict):
    ticker, snapshot = _v22_2_normalize_technical_payload(payload)

    store = _v22_2_safe_read_json(_V22_2_TECH_FILE, {})
    if not isinstance(store, dict):
        store = {}

    store[ticker] = snapshot
    ok = _v22_2_safe_write_json(_V22_2_TECH_FILE, store)

    return {
        "engine": "V22_2_REMOTE_SNAPSHOT_SYNC",
        "type": "technical",
        "status": "OK" if ok else "WRITE_FAILED",
        "ticker": ticker,
        "technical_snapshot_available": bool(store),
        "technical_tickers": sorted(list(store.keys())),
        "path": str(_V22_2_TECH_FILE),
        "received_at": snapshot.get("received_at"),
    }

@app.post("/v22_2_ingest_decision_snapshot")
def v22_2_ingest_decision_snapshot(payload: dict):
    data = _v22_2_normalize_decision_payload(payload)
    ok = _v22_2_safe_write_json(_V22_2_DECISION_FILE, data)

    return {
        "engine": "V22_2_REMOTE_SNAPSHOT_SYNC",
        "type": "decision",
        "status": "OK" if ok else "WRITE_FAILED",
        "decision_snapshot_available": ok,
        "rows_found": len(data.get("rows") or data.get("top") or []),
        "path": str(_V22_2_DECISION_FILE),
        "received_at": data.get("received_at"),
    }

@app.post("/v22_2_ingest_unified_snapshot")
def v22_2_ingest_unified_snapshot(payload: dict):
    data = dict(payload or {})
    data["received_at"] = _v22_2_now_iso()
    data["source"] = data.get("source") or "REMOTE_V22_2_UNIFIED"
    ok = _v22_2_safe_write_json(_V22_2_UNIFIED_FILE, data)

    return {
        "engine": "V22_2_REMOTE_SNAPSHOT_SYNC",
        "type": "unified",
        "status": "OK" if ok else "WRITE_FAILED",
        "unified_snapshot_available": ok,
        "ticker": data.get("ticker"),
        "decision": data.get("decision") or data.get("final_state"),
        "can_operate": data.get("can_operate"),
        "path": str(_V22_2_UNIFIED_FILE),
        "received_at": data.get("received_at"),
    }

@app.get("/v22_2_snapshot_status")
def v22_2_snapshot_status():
    technical = _v22_2_safe_read_json(_V22_2_TECH_FILE, {})
    decision = _v22_2_safe_read_json(_V22_2_DECISION_FILE, {})
    unified = _v22_2_safe_read_json(_V22_2_UNIFIED_FILE, {})

    if not isinstance(technical, dict):
        technical = {}
    if not isinstance(decision, dict):
        decision = {}
    if not isinstance(unified, dict):
        unified = {}

    return {
        "engine": "V22_2_REMOTE_SNAPSHOT_SYNC",
        "status": "OK",
        "technical_snapshot_available": bool(technical),
        "technical_tickers": sorted(list(technical.keys())),
        "decision_snapshot_available": bool(decision),
        "unified_snapshot_available": bool(unified),
        "decision_rows_found": len(decision.get("rows") or decision.get("top") or []),
        "files": {
            "technical": str(_V22_2_TECH_FILE),
            "decision": str(_V22_2_DECISION_FILE),
            "unified": str(_V22_2_UNIFIED_FILE),
        },
    }

@app.get("/v22_2_technical_snapshot/{ticker}")
def v22_2_technical_snapshot(ticker: str):
    ticker = ticker.upper().strip()
    technical = _v22_2_safe_read_json(_V22_2_TECH_FILE, {})
    if not isinstance(technical, dict):
        technical = {}

    snap = technical.get(ticker)
    return {
        "engine": "V22_2_REMOTE_SNAPSHOT_SYNC",
        "ticker": ticker,
        "status": "OK" if snap else "NO_TECHNICAL_SNAPSHOT_FOR_TICKER",
        "snapshot": snap,
        "available_tickers": sorted(list(technical.keys())),
    }

@app.get("/v22_2_decision_snapshot")
def v22_2_decision_snapshot():
    decision = _v22_2_safe_read_json(_V22_2_DECISION_FILE, {})
    return {
        "engine": "V22_2_REMOTE_SNAPSHOT_SYNC",
        "status": "OK" if decision else "NO_DECISION_SNAPSHOT",
        "snapshot": decision,
    }

@app.get("/v22_2_trade_decision/{ticker}")
def v22_2_trade_decision(ticker: str):
    ticker = ticker.upper().strip()
    technical = _v22_2_safe_read_json(_V22_2_TECH_FILE, {})
    decision = _v22_2_safe_read_json(_V22_2_DECISION_FILE, {})
    unified = _v22_2_safe_read_json(_V22_2_UNIFIED_FILE, {})

    if not isinstance(technical, dict):
        technical = {}
    if not isinstance(decision, dict):
        decision = {}
    if not isinstance(unified, dict):
        unified = {}

    tech = technical.get(ticker)

    rows = decision.get("rows") or decision.get("top") or []
    ticker_rows = []
    if isinstance(rows, list):
        for r in rows:
            if isinstance(r, dict) and str(r.get("ticker", "")).upper() == ticker:
                ticker_rows.append(r)

    best = ticker_rows[0] if ticker_rows else None

    final_state = "NO_DATA"
    decision_text = "No hay datos suficientes para tomar decisión."
    can_operate = False
    main_blocker = "NO_REMOTE_DATA"

    if not tech and not best:
        final_state = "NO_DATA"
        main_blocker = "NO_TECHNICAL_OR_OPTIONS_DATA"
        decision_text = f"{ticker}: no hay snapshot técnico ni snapshot operativo disponible todavía."
    elif tech and not best:
        final_state = "TECH_ONLY"
        main_blocker = "NO_OPTIONS_DECISION_ROW"
        decision_text = f"{ticker}: hay snapshot técnico, pero no hay oportunidad de opciones capturada."
    elif best:
        base_decision = str(best.get("decision") or best.get("final_state") or "RADAR").upper()
        missing = best.get("missing_confirmations") or best.get("missing_data") or best.get("falta") or []
        if isinstance(missing, str):
            missing = [missing]

        market_hours = decision.get("market_hours") or {}
        market_status = str(market_hours.get("status") or "").upper()
        options_expected = bool(market_hours.get("options_bidask_expected", False))

        can_operate = bool(best.get("can_operate", False))

        if market_status and market_status != "REGULAR":
            final_state = "WAIT_MARKET_OPEN"
            main_blocker = "OPTIONS_MARKET_NOT_RELIABLE"
            decision_text = f"{ticker}: oportunidad en radar, pero no operar ahora. Revisar próxima sesión después de 09:35 ET."
            can_operate = False
        elif missing:
            final_state = "RADAR_CONFIRMATION_PENDING"
            main_blocker = ",".join(missing)
            decision_text = f"{ticker}: mantener en radar. Falta confirmar: {', '.join(missing)}."
            can_operate = False
        elif base_decision in ("ENTRY", "ENTRY_CONFIRMED", "OPERAR") and can_operate:
            final_state = "ENTRY_CONFIRMED"
            main_blocker = None
            decision_text = f"{ticker}: entrada confirmada según snapshot remoto."
        else:
            final_state = base_decision
            main_blocker = best.get("main_blocker") or "NOT_ENTRY_CONFIRMED"
            decision_text = best.get("recommendation") or best.get("action") or f"{ticker}: mantener en observación."

    return {
        "engine": "V22_2_REMOTE_SNAPSHOT_SYNC",
        "ticker": ticker,
        "status": "OK",
        "final_state": final_state,
        "decision": final_state,
        "can_operate": can_operate,
        "main_blocker": main_blocker,
        "action": decision_text,
        "executive_summary": decision_text,
        "technical_available": bool(tech),
        "options_rows_found": len(ticker_rows),
        "technical": tech,
        "best_row": best,
        "market_hours": decision.get("market_hours") if isinstance(decision, dict) else None,
        "generated_at": _v22_2_now_iso(),
    }
'''

if "V22.2 REMOTE SNAPSHOT SYNC" not in app:
    app = app.rstrip() + "\n\n" + v22_2_app_block + "\n"
    APP.write_text(app)

# ============================================================
# V22.2 IBRK BRIDGE PATCH — POST LOCAL SNAPSHOTS TO RENDER
# ============================================================

v22_2_bridge_block = r'''
# ============================================================
# V22.2 REMOTE SNAPSHOT SYNC — LOCAL BRIDGE POST TO RENDER
# ============================================================

import json as _v22_2_json
from pathlib import Path as _v22_2_Path
from datetime import datetime as _v22_2_datetime, timezone as _v22_2_timezone

try:
    import requests as _v22_2_requests
except Exception:
    _v22_2_requests = None

V22_2_REMOTE_BASE_URL = "https://trading-engine-p097.onrender.com"

def _v22_2_now_iso():
    return _v22_2_datetime.now(_v22_2_timezone.utc).isoformat()

def _v22_2_read_json_file(path):
    try:
        p = _v22_2_Path(path)
        if p.exists():
            return _v22_2_json.loads(p.read_text())
    except Exception:
        pass
    return None

def _v22_2_post_json(endpoint, payload, timeout=8):
    if _v22_2_requests is None:
        return {"ok": False, "status": "NO_REQUESTS_LIB", "url": endpoint}

    url = V22_2_REMOTE_BASE_URL.rstrip("/") + endpoint
    try:
        r = _v22_2_requests.post(url, json=payload, timeout=timeout)
        try:
            body = r.json()
        except Exception:
            body = {"text": r.text[:500]}
        return {
            "ok": 200 <= r.status_code < 300,
            "status": r.status_code,
            "url": url,
            "body": body,
        }
    except Exception as e:
        return {
            "ok": False,
            "status": "POST_ERROR",
            "url": url,
            "error": str(e),
        }

def _v22_2_collect_candidate_files():
    return {
        "technical": [
            "runtime/technical_snapshot_by_ticker_safe.json",
            "runtime/technical_snapshot_by_ticker.json",
            "technical_snapshot_by_ticker_safe.json",
            "technical_snapshot_by_ticker.json",
        ],
        "decision": [
            "runtime/decision_desk_snapshot.json",
            "runtime/v18_decision_snapshot.json",
            "runtime/v18_decision_desk_snapshot.json",
            "decision_desk_snapshot.json",
            "decision_snapshot.json",
        ],
    }

def _v22_2_find_first_json(paths):
    for p in paths:
        data = _v22_2_read_json_file(p)
        if data:
            return p, data
    return None, None

def _v22_2_remote_sync_snapshots(extra_payload=None):
    files = _v22_2_collect_candidate_files()

    tech_path, tech_data = _v22_2_find_first_json(files["technical"])
    decision_path, decision_data = _v22_2_find_first_json(files["decision"])

    results = {
        "engine": "V22_2_REMOTE_SNAPSHOT_SYNC",
        "generated_at": _v22_2_now_iso(),
        "technical_path": tech_path,
        "decision_path": decision_path,
        "technical_sent": False,
        "decision_sent": False,
        "unified_sent": False,
        "responses": {},
    }

    if isinstance(tech_data, dict):
        # Caso A: store por ticker {"QQQ": {...}, "SPY": {...}}
        if any(isinstance(v, dict) for v in tech_data.values()):
            for ticker, snap in tech_data.items():
                if isinstance(snap, dict):
                    payload = {
                        "ticker": str(ticker).upper(),
                        "snapshot": snap,
                        "source": "IBKR_BRIDGE_V22_2_REMOTE_SYNC",
                        "local_path": tech_path,
                    }
                    resp = _v22_2_post_json("/v22_2_ingest_technical_snapshot", payload)
                    results["responses"][f"technical_{ticker}"] = resp
                    if resp.get("ok"):
                        results["technical_sent"] = True
        # Caso B: snapshot directo {"ticker":"QQQ", ...}
        elif tech_data.get("ticker"):
            payload = {
                "ticker": str(tech_data.get("ticker")).upper(),
                "snapshot": tech_data,
                "source": "IBKR_BRIDGE_V22_2_REMOTE_SYNC",
                "local_path": tech_path,
            }
            resp = _v22_2_post_json("/v22_2_ingest_technical_snapshot", payload)
            results["responses"]["technical_single"] = resp
            if resp.get("ok"):
                results["technical_sent"] = True

    if isinstance(decision_data, dict):
        payload = dict(decision_data)
        payload["source"] = payload.get("source") or "IBKR_BRIDGE_V22_2_REMOTE_SYNC"
        payload["local_path"] = decision_path
        resp = _v22_2_post_json("/v22_2_ingest_decision_snapshot", payload)
        results["responses"]["decision"] = resp
        if resp.get("ok"):
            results["decision_sent"] = True

    unified_payload = {
        "engine": "V22_2_REMOTE_SNAPSHOT_SYNC",
        "generated_at": _v22_2_now_iso(),
        "technical_available": bool(tech_data),
        "decision_available": bool(decision_data),
        "technical_path": tech_path,
        "decision_path": decision_path,
        "extra_payload": extra_payload or {},
        "source": "IBKR_BRIDGE_V22_2_REMOTE_SYNC",
    }
    resp = _v22_2_post_json("/v22_2_ingest_unified_snapshot", unified_payload)
    results["responses"]["unified"] = resp
    if resp.get("ok"):
        results["unified_sent"] = True

    return results

def v22_2_print_remote_sync_status(extra_payload=None):
    try:
        res = _v22_2_remote_sync_snapshots(extra_payload=extra_payload)
        print("")
        print("=== V22.2 REMOTE SNAPSHOT SYNC ===")
        print(f"technical_sent: {res.get('technical_sent')} | path: {res.get('technical_path')}")
        print(f"decision_sent: {res.get('decision_sent')} | path: {res.get('decision_path')}")
        print(f"unified_sent: {res.get('unified_sent')}")
        for k, v in (res.get("responses") or {}).items():
            print(f"{k}: ok={v.get('ok')} status={v.get('status')}")
        print("==================================")
        print("")
        return res
    except Exception as e:
        print(f"V22.2 remote sync error: {e}")
        return {"ok": False, "error": str(e)}
'''

if "V22.2 REMOTE SNAPSHOT SYNC" not in bridge:
    bridge = bridge.rstrip() + "\n\n" + v22_2_bridge_block + "\n"

# Insert call before waiting loop if possible
if "v22_2_print_remote_sync_status" in bridge and "V22.2 REMOTE SYNC CALL INSERTED" not in bridge:
    patterns = [
        r'print\(f"Esperando \{LOOP_SECONDS\} segundos\.\.\."\)',
        r"print\(f'Esperando \{LOOP_SECONDS\} segundos\.\.\.'\)",
        r'print\("Esperando',
    ]

    inserted = False
    for pat in patterns:
        m = re.search(pat, bridge)
        if m:
            insert_pos = m.start()
            call = '''
# V22.2 REMOTE SYNC CALL INSERTED
try:
    v22_2_print_remote_sync_status(extra_payload={"cycle": "auto"})
except Exception as _v22_2_sync_e:
    print(f"V22.2 sync call error: {_v22_2_sync_e}")

'''
            bridge = bridge[:insert_pos] + call + bridge[insert_pos:]
            inserted = True
            break

    if not inserted:
        bridge += '''
# V22.2 REMOTE SYNC CALL INSERTED — fallback location
try:
    v22_2_print_remote_sync_status(extra_payload={"cycle": "fallback"})
except Exception as _v22_2_sync_e:
    print(f"V22.2 sync call error: {_v22_2_sync_e}")
'''

BRIDGE.write_text(bridge)

print("V22.2 Remote Snapshot Sync patch applied.")
