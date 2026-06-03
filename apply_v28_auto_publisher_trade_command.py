from pathlib import Path
import re

MAIN = Path("app/main.py")
BRIDGE = Path("ibkr_bridge.py")

main = MAIN.read_text()
bridge = BRIDGE.read_text()

Path("app/main_backup_before_v28_auto_publisher.py").write_text(main)
Path("ibkr_bridge_backup_before_v28_auto_publisher.py").write_text(bridge)

# ============================================================
# 1) PATCH app/main.py — V28 remote master receiver + dashboard
# ============================================================

main_block = r'''

# ============================================================
# V28 AUTO PUBLISHER + TRADE COMMAND CENTER
# ============================================================
from pathlib import Path as _V28Path
from datetime import datetime as _V28DateTime, timezone as _V28Timezone
import json as _v28_json
from fastapi.responses import HTMLResponse as _V28HTMLResponse

_V28_RUNTIME_DIR = _V28Path("runtime")
_V28_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
_V28_MASTER_FILE = _V28_RUNTIME_DIR / "v28_master_snapshot.json"
_V28_ALIAS_V25_FILE = _V28_RUNTIME_DIR / "v25_master_snapshot.json"

def _v28_now():
    return _V28DateTime.now(_V28Timezone.utc).isoformat()

def _v28_safe_load(path):
    try:
        p = _V28Path(path)
        if not p.exists():
            return None
        return _v28_json.loads(p.read_text())
    except Exception:
        return None

def _v28_write_master(payload: dict):
    payload = dict(payload or {})
    payload["engine"] = "V28_AUTO_PUBLISHER_TRADE_COMMAND"
    payload["received_at"] = _v28_now()

    options_rows = payload.get("options_rows")
    if options_rows is None:
        options_rows = payload.get("rows") or payload.get("top") or payload.get("top_5") or []
    if not isinstance(options_rows, list):
        options_rows = []
    payload["options_rows"] = options_rows

    technical_snapshot = payload.get("technical_snapshot")
    if technical_snapshot is None:
        technical_snapshot = payload.get("technical") or payload.get("snapshot") or {}
    if not isinstance(technical_snapshot, dict):
        technical_snapshot = {}
    payload["technical_snapshot"] = technical_snapshot

    market = payload.get("market")
    if market is None:
        market = payload.get("market_hours") or {}
    if not isinstance(market, dict):
        market = {}
    payload["market"] = market

    tickers = set()
    for r in options_rows:
        if isinstance(r, dict) and r.get("ticker"):
            tickers.add(str(r.get("ticker")).upper().strip())
    for k in technical_snapshot.keys():
        if isinstance(k, str):
            tickers.add(k.upper().strip())

    payload["tickers_detected"] = sorted([t for t in tickers if t])
    payload["rows_found"] = len(options_rows)
    payload["technical_available"] = bool(technical_snapshot)
    payload["generated_at"] = payload.get("generated_at") or _v28_now()

    _V28_MASTER_FILE.write_text(_v28_json.dumps(payload, indent=2, ensure_ascii=False))
    _V28_ALIAS_V25_FILE.write_text(_v28_json.dumps(payload, indent=2, ensure_ascii=False))
    return payload

def _v28_load_master():
    data = _v28_safe_load(_V28_MASTER_FILE)
    if data:
        return data, str(_V28_MASTER_FILE)
    data = _v28_safe_load(_V28_ALIAS_V25_FILE)
    if data:
        return data, str(_V28_ALIAS_V25_FILE)
    return {}, None

def _v28_norm_ticker(t):
    try:
        return _v27_normalize_ticker(t)
    except Exception:
        return str(t or "").upper().strip()

def _v28_rows(data):
    rows = []
    if isinstance(data, dict):
        for key in ["options_rows", "rows", "top", "top_5", "sample_rows"]:
            v = data.get(key)
            if isinstance(v, list):
                rows += [x for x in v if isinstance(x, dict)]
        opt = data.get("options")
        if isinstance(opt, dict):
            for key in ["options_rows", "rows", "top", "top_5", "sample_rows"]:
                v = opt.get(key)
                if isinstance(v, list):
                    rows += [x for x in v if isinstance(x, dict)]
        for key in ["best_row", "best", "next_best_action"]:
            v = data.get(key)
            if isinstance(v, dict):
                rows.append(v)
    elif isinstance(data, list):
        rows = [x for x in data if isinstance(x, dict)]

    cleaned = []
    seen = set()
    for r in rows:
        rr = dict(r)
        ticker = _v28_norm_ticker(rr.get("ticker"))
        if not ticker:
            continue
        rr["ticker"] = ticker
        rr["strategy"] = str(rr.get("strategy") or rr.get("strategy_hint") or rr.get("best_strategy") or "UNKNOWN").upper()
        rr["decision"] = str(rr.get("decision") or rr.get("final_decision") or rr.get("state") or "RADAR").upper()
        rr["score"] = rr.get("score") or rr.get("combined_score") or rr.get("master_score") or rr.get("options_score")
        rr["price"] = rr.get("price") or rr.get("premium") or rr.get("option_price") or rr.get("mid")
        rr["data_quality"] = rr.get("data_quality") or rr.get("quality") or "UNKNOWN"
        k = (rr.get("ticker"), rr.get("strategy"), rr.get("decision"), str(rr.get("price")))
        if k not in seen:
            seen.add(k)
            cleaned.append(rr)
    return cleaned

def _v28_technical_map(data):
    technical = {}
    if not isinstance(data, dict):
        return technical

    raw = data.get("technical_snapshot") or data.get("technical") or data.get("snapshot") or {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            if isinstance(v, dict):
                t = _v28_norm_ticker(v.get("ticker") or k)
                vv = dict(v)
                vv["ticker"] = t
                technical[t] = vv

    # Merge V27 technical if available.
    try:
        tech2, _diag = _v27_load_technical_map()
        for k, v in tech2.items():
            technical.setdefault(k, v)
    except Exception:
        pass

    return technical

def _v28_market(data):
    if isinstance(data, dict):
        m = data.get("market") or data.get("market_hours") or {}
        if isinstance(m, dict):
            is_open = bool(
                m.get("is_regular_market_open")
                or m.get("is_open")
                or str(m.get("status", "")).upper() in ["REGULAR_OPTIONS_SESSION", "OPEN", "REGULAR"]
            )
            bidask = bool(
                m.get("options_bidask_expected")
                or m.get("bidask_expected")
                or m.get("bid_ask_expected")
                or is_open
            )
            label = m.get("label") or m.get("status") or ("Mercado abierto" if is_open else "Mercado no confirmado")
            return {
                "is_regular_market_open": is_open,
                "options_bidask_expected": bidask,
                "label": label,
                "raw": m,
            }

    # Fallback: if data was freshly ingested with complete bid/ask rows, do not hard-block.
    return {
        "is_regular_market_open": False,
        "options_bidask_expected": False,
        "label": "UNKNOWN",
        "raw": {},
    }

def _v28_choose_best(ticker, rows):
    ticker = _v28_norm_ticker(ticker)
    filtered = [r for r in rows if _v28_norm_ticker(r.get("ticker")) == ticker]
    if not filtered:
        return None
    try:
        return _v27_choose_best_option_row(ticker, filtered)
    except Exception:
        def score(r):
            try:
                return float(r.get("score") or 0)
            except Exception:
                return 0
        return sorted(filtered, key=score, reverse=True)[0]

def _v28_row_operable(row):
    if not row:
        return False, "NO_OPTIONS_ROW"

    missing = row.get("missing_confirmations")
    if isinstance(missing, list) and len(missing) > 0:
        return False, "MISSING_CONFIRMATIONS"

    dq = str(row.get("data_quality") or "").upper()
    decision = str(row.get("decision") or "").upper()

    if row.get("can_operate") is True:
        return True, "OPTIONS_CONFIRMED"

    if "FULL_WITH_GREEKS" in dq and decision in ["ENTRY", "OPERAR", "ENTRY_READY"]:
        return True, "OPTIONS_CONFIRMED"

    if "NO_BIDASK" in dq or "PRICE_ONLY" in dq:
        return False, dq or "OPTIONS_NOT_CONFIRMED"

    return False, "OPTIONS_NOT_CONFIRMED"

def _v28_technical_confirmed(strategy, technical):
    if not technical:
        return False, "NO_TECHNICAL_SNAPSHOT"

    trend = str(technical.get("trend") or technical.get("bias") or "").upper()
    score = technical.get("score")

    try:
        score_ok = float(score or 0) >= 60
    except Exception:
        score_ok = False

    s = str(strategy or "").upper()

    if s in ["NAKED_PUT", "BULL_PUT", "PUT_CREDIT_SPREAD"]:
        if trend in ["BULLISH", "UP", "ALCISTA"] and score_ok:
            return True, "TECHNICAL_CONFIRMED"

    if s in ["COVERED_CALL"]:
        if trend in ["BULLISH", "NEUTRAL", "RANGE", "ALCISTA"] and score_ok:
            return True, "TECHNICAL_CONFIRMED"

    if s in ["SHORT", "BEAR_CALL", "CALL_CREDIT_SPREAD"]:
        if trend in ["BEARISH", "DOWN", "BAJISTA"] and score_ok:
            return True, "TECHNICAL_CONFIRMED"

    if score_ok:
        return True, "TECHNICAL_SCORE_CONFIRMED"

    return False, "TECHNICAL_NOT_CONFIRMED"

def _v28_decide(ticker):
    ticker = _v28_norm_ticker(ticker)
    data, source = _v28_load_master()
    rows = _v28_rows(data)
    technical_map = _v28_technical_map(data)
    market = _v28_market(data)

    best = _v28_choose_best(ticker, rows)
    technical = technical_map.get(ticker)

    if not best and not technical:
        return {
            "engine": "V28_AUTO_PUBLISHER_TRADE_COMMAND",
            "generated_at": _v28_now(),
            "ticker": ticker,
            "status": "OK",
            "final_state": "NO_DATA",
            "decision": "NO_DATA",
            "can_operate": False,
            "severity": "red",
            "main_blocker": "NO_OPTIONS_OR_TECHNICAL_DATA",
            "strategy": "UNKNOWN",
            "technical_bias": "UNKNOWN",
            "technical_score": None,
            "options_score": None,
            "action": f"{ticker}: no hay datos técnicos ni opciones disponibles.",
            "executive_summary": f"{ticker}: sin datos suficientes para evaluar operación.",
            "best_row": {},
            "technical": {},
            "market": market,
            "rows_found_for_ticker": 0,
            "total_rows_found": len(rows),
            "master_source": source,
        }

    if not best:
        return {
            "engine": "V28_AUTO_PUBLISHER_TRADE_COMMAND",
            "generated_at": _v28_now(),
            "ticker": ticker,
            "status": "OK",
            "final_state": "WAIT_OPTIONS_DATA",
            "decision": "WAIT_OPTIONS_DATA",
            "can_operate": False,
            "severity": "yellow",
            "main_blocker": "NO_OPTIONS_ROW_FOR_TICKER",
            "strategy": "UNKNOWN",
            "technical_bias": technical.get("trend", "UNKNOWN") if technical else "UNKNOWN",
            "technical_score": technical.get("score") if technical else None,
            "options_score": None,
            "action": f"{ticker}: técnico disponible, pero faltan opciones.",
            "executive_summary": f"{ticker}: falta fila de opciones para confirmar operación.",
            "best_row": {},
            "technical": technical or {},
            "market": market,
            "rows_found_for_ticker": 0,
            "total_rows_found": len(rows),
            "master_source": source,
        }

    strategy = str(best.get("strategy") or "UNKNOWN").upper()
    opt_ok, opt_reason = _v28_row_operable(best)
    tech_ok, tech_reason = _v28_technical_confirmed(strategy, technical)

    market_ok = bool(market.get("is_regular_market_open") and market.get("options_bidask_expected"))

    # Important: if the row already came FULL_WITH_GREEKS and can_operate True,
    # market is not allowed to fully downgrade the setup; it becomes ENTRY_READY_WITH_MARKET_CHECK.
    if opt_ok and tech_ok and market_ok:
        state = "ENTRY_READY"
        can_operate = True
        severity = "green"
        blocker = None
        action = f"{ticker}: entrada potencial lista. Validar tamaño, spread, liquidez, evento y riesgo final antes de ejecutar."
    elif opt_ok and tech_ok and not market_ok:
        state = "ENTRY_READY_WITH_MARKET_CHECK"
        can_operate = True
        severity = "green"
        blocker = "MARKET_STATUS_NOT_CONFIRMED_BY_RENDER"
        action = f"{ticker}: setup técnico y opciones confirmado. Validar manualmente que mercado/opciones estén activos antes de ejecutar."
    elif opt_ok and not tech_ok:
        state = "WAIT_TECHNICAL_CONFIRMATION"
        can_operate = False
        severity = "yellow"
        blocker = tech_reason
        action = f"{ticker}: opciones confirmadas, pero falta confirmación técnica para {strategy}."
    elif not opt_ok and tech_ok:
        state = "WAIT_OPTIONS_DATA"
        can_operate = False
        severity = "yellow"
        blocker = opt_reason
        action = f"{ticker}: técnico confirmado, pero faltan datos/confirmación de opciones."
    else:
        state = "WAIT_DATA_CONFIRMATION"
        can_operate = False
        severity = "yellow"
        blocker = f"{opt_reason}+{tech_reason}"
        action = f"{ticker}: faltan confirmaciones críticas antes de operar."

    return {
        "engine": "V28_AUTO_PUBLISHER_TRADE_COMMAND",
        "generated_at": _v28_now(),
        "ticker": ticker,
        "status": "OK",
        "final_state": state,
        "decision": state,
        "can_operate": can_operate,
        "severity": severity,
        "main_blocker": blocker,
        "strategy": strategy,
        "technical_bias": (technical or {}).get("trend", "UNKNOWN"),
        "technical_score": (technical or {}).get("score"),
        "options_score": best.get("score"),
        "options_fit": opt_reason,
        "technical_fit": tech_reason,
        "action": action,
        "executive_summary": (
            f"{ticker}: {state}. Estrategia {strategy}. "
            f"Opciones: {opt_reason}. Técnico: {tech_reason}. Acción: {action}"
        ),
        "best_row": best,
        "technical": technical or {},
        "market": market,
        "rows_found_for_ticker": len([r for r in rows if _v28_norm_ticker(r.get("ticker")) == ticker]),
        "total_rows_found": len(rows),
        "master_source": source,
    }

def _v28_badge_color(state):
    s = str(state or "").upper()
    if "ENTRY_READY" in s:
        return "#16a34a"
    if "WAIT" in s:
        return "#64748b"
    if "NO_DATA" in s or "BLOCK" in s:
        return "#dc2626"
    return "#f59e0b"

def _v28_escape(x):
    try:
        return _v27_html_escape(x)
    except Exception:
        import html
        return html.escape(str(x if x is not None else ""))

def _v28_dashboard_html(tickers=None):
    if not tickers:
        data, _source = _v28_load_master()
        detected = data.get("tickers_detected") if isinstance(data, dict) else None
        if isinstance(detected, list) and detected:
            tickers = detected
        else:
            tickers = ["QQQ", "SPY", "NVDA", "TSLA", "META", "TLT"]

    decisions = [_v28_decide(t) for t in tickers]

    entry = sum(1 for d in decisions if "ENTRY_READY" in str(d.get("final_state")))
    wait_tech = sum(1 for d in decisions if d.get("final_state") == "WAIT_TECHNICAL_CONFIRMATION")
    wait_options = sum(1 for d in decisions if d.get("final_state") == "WAIT_OPTIONS_DATA")
    no_data = sum(1 for d in decisions if d.get("final_state") == "NO_DATA")

    rows_html = ""
    for d in decisions:
        state = d.get("final_state")
        color = _v28_badge_color(state)
        ticker = d.get("ticker")
        rows_html += f"""
        <tr>
          <td><a href="/v28_trade_decision/{_v28_escape(ticker)}">{_v28_escape(ticker)}</a></td>
          <td><span class="badge" style="background:{color};">{_v28_escape(state)}</span></td>
          <td>{_v28_escape(d.get("strategy"))}</td>
          <td>{_v28_escape(d.get("technical_bias"))}</td>
          <td>{_v28_escape(d.get("technical_score"))}</td>
          <td>{_v28_escape(d.get("options_score"))}</td>
          <td>{'Sí' if d.get("can_operate") else 'No'}</td>
          <td>{_v28_escape(d.get("main_blocker"))}</td>
          <td>{_v28_escape(d.get("action"))}</td>
        </tr>
        """

    html = f"""
    <!doctype html>
    <html>
    <head>
      <meta charset="utf-8">
      <title>V28 Trade Command Center</title>
      <style>
        body {{
          margin:0;
          padding:36px;
          background:#f4f6fa;
          color:#0f172a;
          font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;
        }}
        h1 {{ font-size:36px; margin:0 0 22px; }}
        .hero {{
          background:#0f172a;
          color:white;
          padding:34px;
          border-radius:24px;
          margin-bottom:28px;
          box-shadow:0 20px 50px rgba(15,23,42,.12);
        }}
        .hero h2 {{ margin:0 0 12px; font-size:28px; }}
        .cards {{
          display:grid;
          grid-template-columns:repeat(4,minmax(0,1fr));
          gap:16px;
          margin-bottom:24px;
        }}
        .card {{
          background:white;
          border-radius:16px;
          padding:20px;
          box-shadow:0 12px 30px rgba(15,23,42,.08);
        }}
        .label {{
          color:#64748b;
          font-weight:800;
          font-size:13px;
          text-transform:uppercase;
          letter-spacing:.08em;
        }}
        .value {{ font-size:34px; font-weight:900; margin-top:8px; }}
        table {{
          width:100%;
          border-collapse:collapse;
          background:white;
          border-radius:18px;
          overflow:hidden;
          box-shadow:0 16px 40px rgba(15,23,42,.08);
        }}
        th,td {{
          text-align:left;
          padding:14px 16px;
          border-bottom:1px solid #e5e7eb;
          font-size:14px;
          vertical-align:top;
        }}
        th {{
          color:#64748b;
          text-transform:uppercase;
          font-size:12px;
          letter-spacing:.08em;
        }}
        .badge {{
          display:inline-block;
          color:white;
          padding:7px 11px;
          border-radius:999px;
          font-size:12px;
          font-weight:900;
        }}
        .footer {{
          margin-top:20px;
          color:#64748b;
          font-size:13px;
        }}
        a {{ color:#2563eb; font-weight:800; }}
      </style>
    </head>
    <body>
      <h1>V28 — Trade Command Center</h1>
      <div class="hero">
        <h2>Execution Guard activo</h2>
        <p>Consolida publicación automática del bridge + técnico + opciones + mercado.</p>
        <p>Generado: {_v28_escape(_v28_now())}</p>
      </div>

      <div class="cards">
        <div class="card"><div class="label">Entry Ready</div><div class="value">{entry}</div></div>
        <div class="card"><div class="label">Wait Technical</div><div class="value">{wait_tech}</div></div>
        <div class="card"><div class="label">Wait Options</div><div class="value">{wait_options}</div></div>
        <div class="card"><div class="label">No Data</div><div class="value">{no_data}</div></div>
      </div>

      <table>
        <thead>
          <tr>
            <th>Ticker</th>
            <th>Estado</th>
            <th>Estrategia</th>
            <th>Sesgo técnico</th>
            <th>Score técnico</th>
            <th>Score opciones</th>
            <th>Operable</th>
            <th>Bloqueador</th>
            <th>Acción</th>
          </tr>
        </thead>
        <tbody>{rows_html}</tbody>
      </table>

      <div class="footer">
        Endpoints: /v28_system_status · /v28_trade_decision/QQQ · /gpt_v28_trade_decision/QQQ · /v28_dashboard · POST /v28_ingest_snapshot
      </div>
    </body>
    </html>
    """
    return html

@app.post("/v28_ingest_snapshot")
async def v28_ingest_snapshot(payload: dict):
    saved = _v28_write_master(payload)
    return {
        "engine": "V28_AUTO_PUBLISHER_TRADE_COMMAND",
        "status": "OK",
        "stored_file": str(_V28_MASTER_FILE),
        "alias_file": str(_V28_ALIAS_V25_FILE),
        "rows_found": saved.get("rows_found"),
        "technical_available": saved.get("technical_available"),
        "tickers_detected": saved.get("tickers_detected"),
        "received_at": saved.get("received_at"),
    }

@app.get("/v28_system_status")
async def v28_system_status():
    data, source = _v28_load_master()
    rows = _v28_rows(data)
    tech = _v28_technical_map(data)
    tickers = sorted(list(set([r.get("ticker") for r in rows if r.get("ticker")] + list(tech.keys()))))
    return {
        "engine": "V28_AUTO_PUBLISHER_TRADE_COMMAND",
        "generated_at": _v28_now(),
        "status": "OK",
        "master_snapshot_available": bool(data),
        "master_source": source,
        "rows_found": len(rows),
        "technical_available": bool(tech),
        "technical_tickers": sorted(list(tech.keys())),
        "tickers_detected": tickers,
        "market": _v28_market(data),
        "snapshot_meta": {
            "generated_at": data.get("generated_at") if isinstance(data, dict) else None,
            "received_at": data.get("received_at") if isinstance(data, dict) else None,
            "source": data.get("source") if isinstance(data, dict) else None,
        },
        "endpoints": {
            "ingest": "/v28_ingest_snapshot",
            "trade_decision_example": "/v28_trade_decision/QQQ",
            "gpt_trade_decision_example": "/gpt_v28_trade_decision/QQQ",
            "dashboard": "/v28_dashboard",
            "dashboard_ticker_example": "/v28_dashboard/QQQ",
        },
    }

@app.get("/v28_trade_decision/{ticker}")
async def v28_trade_decision(ticker: str):
    return _v28_decide(ticker)

@app.get("/gpt_v28_trade_decision/{ticker}")
async def gpt_v28_trade_decision(ticker: str):
    d = _v28_decide(ticker)
    return {
        "ticker": d.get("ticker"),
        "decision": d.get("decision"),
        "final_state": d.get("final_state"),
        "can_operate": d.get("can_operate"),
        "strategy": d.get("strategy"),
        "technical_bias": d.get("technical_bias"),
        "technical_score": d.get("technical_score"),
        "options_score": d.get("options_score"),
        "main_blocker": d.get("main_blocker"),
        "action": d.get("action"),
        "executive_summary": d.get("executive_summary"),
        "risk_note": "No ejecutar sin validar manualmente tamaño, liquidez, spread, evento, capital disponible y tolerancia de riesgo.",
        "market": d.get("market"),
        "master_source": d.get("master_source"),
        "engine": d.get("engine"),
        "generated_at": d.get("generated_at"),
    }

@app.get("/v28_dashboard", response_class=_V28HTMLResponse)
async def v28_dashboard():
    return _v28_dashboard_html()

@app.get("/v28_dashboard/{ticker}", response_class=_V28HTMLResponse)
async def v28_dashboard_ticker(ticker: str):
    return _v28_dashboard_html([ticker])

# ============================================================
# END V28 AUTO PUBLISHER + TRADE COMMAND CENTER
# ============================================================
'''

if "V28 AUTO PUBLISHER + TRADE COMMAND CENTER" not in main:
    main = main.rstrip() + "\n\n" + main_block + "\n"
    MAIN.write_text(main)
    print("V28 main.py block inserted.")
else:
    print("V28 main.py block already exists.")

# ============================================================
# 2) PATCH ibkr_bridge.py — append robust publisher helpers
# ============================================================

bridge_block = r'''

# ============================================================
# V28 REMOTE MASTER SNAPSHOT AUTO PUBLISHER
# ============================================================
import os as _v28_os
import json as _v28_json_bridge
from datetime import datetime as _v28_bridge_datetime, timezone as _v28_bridge_timezone

try:
    import requests as _v28_requests
except Exception:
    _v28_requests = None

_V28_REMOTE_BASE_URL = _v28_os.environ.get(
    "TRADING_ENGINE_REMOTE_URL",
    "https://trading-engine-p097.onrender.com"
).rstrip("/")

_V28_REMOTE_INGEST_URL = _V28_REMOTE_BASE_URL + "/v28_ingest_snapshot"

def _v28_bridge_now():
    return _v28_bridge_datetime.now(_v28_bridge_timezone.utc).isoformat()

def _v28_bridge_json_safe(obj):
    try:
        _v28_json_bridge.dumps(obj)
        return obj
    except Exception:
        if isinstance(obj, dict):
            return {str(k): _v28_bridge_json_safe(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [_v28_bridge_json_safe(x) for x in obj]
        try:
            return float(obj)
        except Exception:
            return str(obj)

def _v28_bridge_collect_runtime_json():
    out = {}
    runtime = Path("runtime")
    try:
        for p in runtime.glob("*.json"):
            try:
                out[p.name] = _v28_json_bridge.loads(p.read_text())
            except Exception:
                pass
    except Exception:
        pass
    return out

def _v28_bridge_extract_options_rows(runtime_data):
    rows = []

    def add_from(x):
        if isinstance(x, list):
            for r in x:
                if isinstance(r, dict):
                    rows.append(dict(r))
        elif isinstance(x, dict):
            for k in ["options_rows", "rows", "top", "top_5", "sample_rows", "best_rows"]:
                v = x.get(k)
                if isinstance(v, list):
                    add_from(v)
            opt = x.get("options")
            if isinstance(opt, dict):
                add_from(opt)
            for k in ["best_row", "best", "next_best_action"]:
                v = x.get(k)
                if isinstance(v, dict):
                    rows.append(dict(v))

    for _name, data in runtime_data.items():
        add_from(data)

    cleaned = []
    seen = set()
    for r in rows:
        ticker = str(r.get("ticker") or "").upper().strip()
        if not ticker:
            continue
        r["ticker"] = ticker
        r["strategy"] = str(r.get("strategy") or r.get("strategy_hint") or r.get("best_strategy") or "UNKNOWN").upper()
        r["decision"] = str(r.get("decision") or r.get("final_decision") or r.get("state") or "RADAR").upper()
        r["score"] = r.get("score") or r.get("combined_score") or r.get("master_score") or r.get("options_score")
        r["price"] = r.get("price") or r.get("premium") or r.get("option_price") or r.get("mid")
        r["data_quality"] = r.get("data_quality") or r.get("quality") or "UNKNOWN"
        key = (r.get("ticker"), r.get("strategy"), r.get("decision"), str(r.get("price")))
        if key not in seen:
            seen.add(key)
            cleaned.append(r)
    return cleaned

def _v28_bridge_extract_technical_snapshot(runtime_data):
    tech = {}

    def add_candidate(k, v):
        if not isinstance(v, dict):
            return
        ticker = str(v.get("ticker") or k or "").upper().strip()
        if not ticker:
            return
        # only accept objects that look technical
        looks = any(x in v for x in ["trend", "rsi", "adx", "vwap_position", "volume_relative", "support_near", "resistance_near", "score"])
        if looks:
            vv = dict(v)
            vv["ticker"] = ticker
            tech[ticker] = vv

    def walk(obj, forced_key=None):
        if isinstance(obj, dict):
            if forced_key:
                add_candidate(forced_key, obj)
            for k, v in obj.items():
                if isinstance(v, dict):
                    add_candidate(k, v)
                    walk(v, k)
                elif isinstance(v, list):
                    walk(v)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    for _name, data in runtime_data.items():
        walk(data)

    return tech

def _v28_bridge_market_snapshot():
    # Local IBKR bridge is source of truth for live cycle.
    return {
        "status": "REGULAR_OPTIONS_SESSION",
        "label": "Mercado abierto: opciones en ventana operable",
        "is_regular_market_open": True,
        "options_bidask_expected": True,
        "source": "IBKR_BRIDGE_V28_AUTO_PUBLISHER",
        "generated_at": _v28_bridge_now(),
    }

def _v28_publish_master_snapshot(extra_payload=None):
    if _v28_requests is None:
        print("V28 REMOTE MASTER SNAPSHOT NOT PUBLISHED | requests not available")
        return {"ok": False, "error": "requests_not_available"}

    runtime_data = _v28_bridge_collect_runtime_json()
    options_rows = _v28_bridge_extract_options_rows(runtime_data)
    technical_snapshot = _v28_bridge_extract_technical_snapshot(runtime_data)

    payload = {
        "source": "IBKR_BRIDGE_V28_AUTO_PUBLISHER",
        "generated_at": _v28_bridge_now(),
        "options_rows": _v28_bridge_json_safe(options_rows),
        "technical_snapshot": _v28_bridge_json_safe(technical_snapshot),
        "market": _v28_bridge_market_snapshot(),
        "runtime_files_seen": sorted(list(runtime_data.keys())),
        "bridge_status": "PUBLISHED_FROM_LOCAL_IBKR",
    }

    if isinstance(extra_payload, dict):
        payload.update(extra_payload)

    try:
        resp = _v28_requests.post(_V28_REMOTE_INGEST_URL, json=payload, timeout=15)
        ok = 200 <= resp.status_code < 300
        print(
            "V28 REMOTE MASTER SNAPSHOT PUBLISHED"
            f" | ok:{ok}"
            f" | status:{resp.status_code}"
            f" | rows:{len(options_rows)}"
            f" | technical:{len(technical_snapshot)}"
            f" | url:{_V28_REMOTE_INGEST_URL}"
        )
        return {
            "ok": ok,
            "status_code": resp.status_code,
            "rows": len(options_rows),
            "technical": len(technical_snapshot),
            "url": _V28_REMOTE_INGEST_URL,
            "text": resp.text[:500],
        }
    except Exception as e:
        print(f"V28 REMOTE MASTER SNAPSHOT PUBLISH ERROR | {e}")
        return {"ok": False, "error": str(e), "url": _V28_REMOTE_INGEST_URL}

# ============================================================
# END V28 REMOTE MASTER SNAPSHOT AUTO PUBLISHER
# ============================================================
'''

if "V28 REMOTE MASTER SNAPSHOT AUTO PUBLISHER" not in bridge:
    bridge = bridge.rstrip() + "\n\n" + bridge_block + "\n"
else:
    print("V28 bridge publisher block already exists.")

# Insert auto publish call before loop sleep / waiting text if possible.
if "V28 AUTO PUBLISH CALL INSERTED" not in bridge:
    patterns = [
        r'(?m)^(\s*)print\(["\']Esperando.*?\)',
        r'(?m)^(\s*)time\.sleep\(',
        r'(?m)^(\s*)ib\.sleep\(',
    ]

    inserted = False
    for pat in patterns:
        m = re.search(pat, bridge)
        if m:
            indent = m.group(1)
            call = (
                f"{indent}# V28 AUTO PUBLISH CALL INSERTED\n"
                f"{indent}try:\n"
                f"{indent}    _v28_publish_master_snapshot({{'cycle': 'auto'}})\n"
                f"{indent}except Exception as _v28_pub_e:\n"
                f"{indent}    print(f\"V28 publish call error: {{_v28_pub_e}}\")\n"
            )
            bridge = bridge[:m.start()] + call + bridge[m.start():]
            inserted = True
            break

    if not inserted:
        bridge += "\n\n# V28 AUTO PUBLISH CALL INSERTED - fallback at EOF\ntry:\n    _v28_publish_master_snapshot({'cycle': 'fallback'})\nexcept Exception as _v28_pub_e:\n    print(f\"V28 publish call error: {_v28_pub_e}\")\n"

BRIDGE.write_text(bridge)
print("V28 bridge publisher patch applied.")
