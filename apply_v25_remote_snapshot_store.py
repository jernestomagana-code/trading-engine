from pathlib import Path
import re

p = Path("app/main.py")
s = p.read_text()

backup = Path("app/main_backup_before_v25_remote_snapshot_store.py")
backup.write_text(s)

block = r'''
# === V25 REMOTE SNAPSHOT STORE / UNIFIED INGEST ===
from pathlib import Path as _V25Path
from datetime import datetime as _V25DateTime, timezone as _V25Timezone
import json as _v25_json

_V25_RUNTIME_DIR = _V25Path("runtime")
_V25_RUNTIME_DIR.mkdir(exist_ok=True)

_V25_MASTER_FILE = _V25_RUNTIME_DIR / "v25_master_snapshot.json"


def _v25_now_iso():
    return _V25DateTime.now(_V25Timezone.utc).isoformat()


def _v25_safe_read_json(path, default=None):
    if default is None:
        default = {}
    try:
        p = _V25Path(path)
        if not p.exists():
            return default
        return _v25_json.loads(p.read_text())
    except Exception:
        return default


def _v25_safe_write_json(path, payload):
    p = _V25Path(path)
    p.parent.mkdir(exist_ok=True)
    p.write_text(_v25_json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return str(p)


def _v25_load_master():
    return _v25_safe_read_json(_V25_MASTER_FILE, default={})


def _v25_extract_rows(snapshot):
    if not isinstance(snapshot, dict):
        return []

    possible_keys = [
        "options_rows",
        "rows",
        "top",
        "top_5",
        "opportunities",
        "decision_rows",
        "sample_rows",
    ]

    for k in possible_keys:
        v = snapshot.get(k)
        if isinstance(v, list):
            return v

    options = snapshot.get("options")
    if isinstance(options, dict):
        for k in possible_keys:
            v = options.get(k)
            if isinstance(v, list):
                return v

    decision = snapshot.get("decision")
    if isinstance(decision, dict):
        for k in possible_keys:
            v = decision.get(k)
            if isinstance(v, list):
                return v

    return []


def _v25_extract_technical(snapshot):
    if not isinstance(snapshot, dict):
        return {}

    tech = snapshot.get("technical_snapshot")
    if isinstance(tech, dict):
        return tech

    tech = snapshot.get("technical")
    if isinstance(tech, dict):
        return tech

    safe = _v25_safe_read_json("runtime/technical_snapshot_by_ticker_safe.json", default={})
    if isinstance(safe, dict):
        return safe

    return {}


def _v25_extract_market(snapshot):
    if not isinstance(snapshot, dict):
        return {}
    market = snapshot.get("market_data")
    if isinstance(market, dict):
        return market
    market = snapshot.get("market")
    if isinstance(market, dict):
        return market
    return {}


def _v25_extract_portfolio(snapshot):
    if not isinstance(snapshot, dict):
        return {}
    portfolio = snapshot.get("portfolio")
    if isinstance(portfolio, dict):
        return portfolio
    return {}


def _v25_ticker_upper(ticker):
    return str(ticker or "").upper().strip()


def _v25_rows_for_ticker(rows, ticker):
    t = _v25_ticker_upper(ticker)
    out = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        rt = _v25_ticker_upper(r.get("ticker") or r.get("symbol") or r.get("underlying"))
        if rt == t:
            out.append(r)
    return out


def _v25_best_row(rows):
    if not rows:
        return None

    def score_key(r):
        if not isinstance(r, dict):
            return -999999
        for k in ["combined_score", "score", "master_score", "technical_score"]:
            try:
                if r.get(k) is not None:
                    return float(r.get(k))
            except Exception:
                pass
        return 0

    return sorted(rows, key=score_key, reverse=True)[0]


def _v25_get_technical_for_ticker(technical, ticker):
    t = _v25_ticker_upper(ticker)
    if not isinstance(technical, dict):
        return {}

    direct = technical.get(t)
    if isinstance(direct, dict):
        return direct

    snap = technical.get("snapshot")
    if isinstance(snap, dict):
        direct = snap.get(t)
        if isinstance(direct, dict):
            return direct

    by_ticker = technical.get("by_ticker")
    if isinstance(by_ticker, dict):
        direct = by_ticker.get(t)
        if isinstance(direct, dict):
            return direct

    return {}


def _v25_has_bullish_technical(tech):
    if not isinstance(tech, dict):
        return False

    trend = str(tech.get("trend") or tech.get("bias") or "").upper()
    score = tech.get("score")
    rsi = tech.get("rsi")
    adx = tech.get("adx")
    support_near = tech.get("support_near")
    resistance_near = tech.get("resistance_near")

    try:
        score_ok = score is not None and float(score) >= 70
    except Exception:
        score_ok = False

    try:
        rsi_ok = rsi is not None and 45 <= float(rsi) <= 70
    except Exception:
        rsi_ok = False

    try:
        adx_ok = adx is not None and float(adx) >= 18
    except Exception:
        adx_ok = False

    trend_ok = trend in ["BULLISH", "ALCISTA", "UP", "LONG"]

    return bool(trend_ok and (score_ok or rsi_ok or adx_ok or support_near is True) and resistance_near is not True)


def _v25_has_bearish_technical(tech):
    if not isinstance(tech, dict):
        return False

    trend = str(tech.get("trend") or tech.get("bias") or "").upper()
    score = tech.get("score")
    rsi = tech.get("rsi")
    adx = tech.get("adx")
    resistance_near = tech.get("resistance_near")
    support_near = tech.get("support_near")

    try:
        score_ok = score is not None and float(score) >= 70
    except Exception:
        score_ok = False

    try:
        rsi_ok = rsi is not None and 30 <= float(rsi) <= 55
    except Exception:
        rsi_ok = False

    try:
        adx_ok = adx is not None and float(adx) >= 18
    except Exception:
        adx_ok = False

    trend_ok = trend in ["BEARISH", "BAJISTA", "DOWN", "SHORT"]

    return bool(trend_ok and (score_ok or rsi_ok or adx_ok or resistance_near is True) and support_near is not True)


def _v25_market_hours():
    # Prefer existing market-hours endpoint if available indirectly through runtime behavior.
    # Conservative fallback: unknown/open. Final decision still requires live options rows.
    return {
        "status": "UNKNOWN",
        "label": "Market hours no confirmado por V25",
        "is_regular_market_open": None,
        "options_bidask_expected": None,
        "generated_at": _v25_now_iso(),
    }


def _v25_make_decision(ticker):
    t = _v25_ticker_upper(ticker)
    master = _v25_load_master()

    rows = _v25_extract_rows(master)
    technical = _v25_extract_technical(master)
    market = _v25_extract_market(master)
    portfolio = _v25_extract_portfolio(master)

    ticker_rows = _v25_rows_for_ticker(rows, t)
    best = _v25_best_row(ticker_rows)
    tech = _v25_get_technical_for_ticker(technical, t)

    if not master:
        return {
            "engine": "V25_REMOTE_SNAPSHOT_STORE",
            "ticker": t,
            "status": "NO_MASTER_SNAPSHOT",
            "final_state": "NO_DATA",
            "decision": "NO_DATA",
            "can_operate": False,
            "severity": "red",
            "main_blocker": "NO_V25_MASTER_SNAPSHOT",
            "action": f"{t}: no hay v25_master_snapshot.json todavía. Ejecutar ibkr_bridge.py o enviar POST /v25_ingest_snapshot.",
            "generated_at": _v25_now_iso(),
        }

    if not ticker_rows:
        return {
            "engine": "V25_REMOTE_SNAPSHOT_STORE",
            "ticker": t,
            "status": "NO_ROWS_FOR_TICKER",
            "final_state": "NO_DATA",
            "decision": "NO_DATA",
            "can_operate": False,
            "severity": "red",
            "main_blocker": "NO_OPTIONS_ROWS_FOR_TICKER",
            "action": f"{t}: hay snapshot maestro, pero no hay rows de opciones para este ticker.",
            "technical": tech,
            "snapshot_meta": {
                "generated_at": master.get("generated_at"),
                "received_at": master.get("received_at"),
                "source": master.get("source"),
            },
            "generated_at": _v25_now_iso(),
        }

    strategy = str((best or {}).get("strategy") or (best or {}).get("strategy_hint") or "UNKNOWN").upper()
    operational_decision = str((best or {}).get("decision") or (best or {}).get("final_decision") or "").upper()
    can_operate_row = bool((best or {}).get("can_operate") is True)
    data_quality = str((best or {}).get("data_quality") or "").upper()
    missing = (best or {}).get("missing_confirmations") or []

    bullish = _v25_has_bullish_technical(tech)
    bearish = _v25_has_bearish_technical(tech)

    technical_fit = "UNKNOWN"
    if strategy in ["NAKED_PUT", "BULL_PUT", "PUT_CREDIT_SPREAD", "CASH_SECURED_PUT"]:
        technical_fit = "CONFIRMED" if bullish else "NOT_CONFIRMED"
    elif strategy in ["COVERED_CALL", "BEAR_CALL", "CALL_CREDIT_SPREAD"]:
        technical_fit = "CONFIRMED" if bearish else "NOT_CONFIRMED"

    full_greeks = "FULL_WITH_GREEKS" in data_quality or not missing
    entry_like = operational_decision in ["ENTRY", "ENTRY_READY", "OPERAR", "READY"]

    if can_operate_row and full_greeks and technical_fit == "CONFIRMED":
        final_state = "ENTRY_READY"
        decision = "ENTRY_READY"
        can_operate = True
        severity = "green"
        main_blocker = None
        action = f"{t}: posible entrada. Validar tamaño, spread, liquidez y riesgo final antes de ejecutar."
    elif can_operate_row and full_greeks and technical_fit != "CONFIRMED":
        final_state = "WAIT_TECHNICAL_CONFIRMATION"
        decision = "WAIT_TECHNICAL_CONFIRMATION"
        can_operate = False
        severity = "yellow"
        main_blocker = "TECHNICAL_NOT_CONFIRMED"
        action = f"{t}: opciones operables, pero falta confirmación técnica para estrategia {strategy}."
    elif ticker_rows:
        final_state = "RADAR"
        decision = "RADAR"
        can_operate = False
        severity = "gray"
        main_blocker = "NOT_FULLY_CONFIRMED"
        action = f"{t}: mantener en radar. Validar greeks, bid/ask, spread, liquidez y confirmación técnica."
    else:
        final_state = "NO_DATA"
        decision = "NO_DATA"
        can_operate = False
        severity = "red"
        main_blocker = "NO_DATA"
        action = f"{t}: sin datos suficientes."

    return {
        "engine": "V25_REMOTE_SNAPSHOT_STORE",
        "ticker": t,
        "status": "OK",
        "final_state": final_state,
        "decision": decision,
        "can_operate": can_operate,
        "severity": severity,
        "main_blocker": main_blocker,
        "action": action,
        "strategy": strategy,
        "technical_fit": technical_fit,
        "technical": tech,
        "best_row": best,
        "rows_found_for_ticker": len(ticker_rows),
        "total_rows_found": len(rows),
        "market": market,
        "portfolio_available": bool(portfolio),
        "snapshot_meta": {
            "generated_at": master.get("generated_at"),
            "received_at": master.get("received_at"),
            "source": master.get("source"),
        },
        "generated_at": _v25_now_iso(),
    }


def _v25_html_escape(x):
    return (
        str(x)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


@app.post("/v25_ingest_snapshot")
async def v25_ingest_snapshot(payload: dict):
    now = _v25_now_iso()

    if not isinstance(payload, dict):
        payload = {"raw_payload": payload}

    normalized = dict(payload)
    normalized["received_at"] = now
    normalized["engine"] = "V25_REMOTE_SNAPSHOT_STORE"

    rows = _v25_extract_rows(normalized)
    technical = _v25_extract_technical(normalized)

    tickers = set()
    for r in rows:
        if isinstance(r, dict):
            tk = _v25_ticker_upper(r.get("ticker") or r.get("symbol") or r.get("underlying"))
            if tk:
                tickers.add(tk)

    if isinstance(technical, dict):
        for k in technical.keys():
            if isinstance(k, str) and len(k) <= 8 and k.upper() == k:
                tickers.add(k)

    normalized["v25_diagnostics"] = {
        "rows_found": len(rows),
        "technical_available": bool(technical),
        "tickers_detected": sorted(tickers),
        "stored_at": now,
    }

    path = _v25_safe_write_json(_V25_MASTER_FILE, normalized)

    return {
        "engine": "V25_REMOTE_SNAPSHOT_STORE",
        "status": "OK",
        "stored_file": path,
        "rows_found": len(rows),
        "technical_available": bool(technical),
        "tickers_detected": sorted(tickers),
        "received_at": now,
    }


@app.get("/v25_system_status")
async def v25_system_status():
    master = _v25_load_master()
    rows = _v25_extract_rows(master)
    technical = _v25_extract_technical(master)

    tickers = set()
    for r in rows:
        if isinstance(r, dict):
            tk = _v25_ticker_upper(r.get("ticker") or r.get("symbol") or r.get("underlying"))
            if tk:
                tickers.add(tk)

    if isinstance(technical, dict):
        for k in technical.keys():
            if isinstance(k, str) and len(k) <= 8 and k.upper() == k:
                tickers.add(k)

    return {
        "engine": "V25_REMOTE_SNAPSHOT_STORE",
        "status": "OK" if bool(master) else "NO_MASTER_SNAPSHOT",
        "master_snapshot_available": bool(master),
        "master_file": str(_V25_MASTER_FILE),
        "rows_found": len(rows),
        "technical_available": bool(technical),
        "tickers_detected": sorted(tickers),
        "snapshot_meta": {
            "generated_at": master.get("generated_at") if isinstance(master, dict) else None,
            "received_at": master.get("received_at") if isinstance(master, dict) else None,
            "source": master.get("source") if isinstance(master, dict) else None,
        },
        "endpoints": {
            "ingest": "/v25_ingest_snapshot",
            "status": "/v25_system_status",
            "decision_example": "/v25_trade_decision/QQQ",
            "dashboard": "/v25_dashboard",
            "dashboard_ticker_example": "/v25_dashboard/QQQ",
        },
        "generated_at": _v25_now_iso(),
    }


@app.get("/v25_trade_decision/{ticker}")
async def v25_trade_decision(ticker: str):
    return _v25_make_decision(ticker)


@app.get("/v25_dashboard")
async def v25_dashboard():
    master = _v25_load_master()
    rows = _v25_extract_rows(master)
    technical = _v25_extract_technical(master)

    tickers = set()
    for r in rows:
        if isinstance(r, dict):
            tk = _v25_ticker_upper(r.get("ticker") or r.get("symbol") or r.get("underlying"))
            if tk:
                tickers.add(tk)

    if isinstance(technical, dict):
        for k in technical.keys():
            if isinstance(k, str) and len(k) <= 8 and k.upper() == k:
                tickers.add(k)

    if not tickers:
        tickers = {"QQQ"}

    decisions = [_v25_make_decision(t) for t in sorted(tickers)]

    rows_html = ""
    for d in decisions:
        sev = d.get("severity", "gray")
        color = {"green": "#16a34a", "yellow": "#ca8a04", "red": "#dc2626", "gray": "#64748b"}.get(sev, "#64748b")
        rows_html += f"""
        <tr>
          <td><a href="/v25_dashboard/{_v25_html_escape(d.get('ticker'))}">{_v25_html_escape(d.get('ticker'))}</a></td>
          <td><span class="pill" style="background:{color};">{_v25_html_escape(d.get('final_state'))}</span></td>
          <td>{_v25_html_escape(d.get('strategy'))}</td>
          <td>{_v25_html_escape(d.get('technical_fit'))}</td>
          <td>{_v25_html_escape(d.get('rows_found_for_ticker'))}</td>
          <td>{'Sí' if d.get('can_operate') else 'No'}</td>
          <td>{_v25_html_escape(d.get('main_blocker'))}</td>
          <td>{_v25_html_escape(d.get('action'))}</td>
        </tr>
        """

    html = f"""
    <html>
    <head>
      <title>V25 Remote Snapshot Store</title>
      <style>
        body {{ font-family: Inter, Arial, sans-serif; background:#f5f7fb; color:#0f172a; margin:0; padding:32px; }}
        h1 {{ font-size:34px; margin-bottom:18px; }}
        .hero {{ background:#0f172a; color:white; border-radius:26px; padding:34px; margin-bottom:24px; }}
        .grid {{ display:grid; grid-template-columns: repeat(4, 1fr); gap:16px; margin-bottom:24px; }}
        .card {{ background:white; border-radius:18px; padding:20px; box-shadow:0 12px 30px rgba(15,23,42,.08); }}
        .num {{ font-size:32px; font-weight:800; }}
        table {{ width:100%; border-collapse:collapse; background:white; border-radius:18px; overflow:hidden; box-shadow:0 12px 30px rgba(15,23,42,.08); }}
        th, td {{ text-align:left; padding:14px 16px; border-bottom:1px solid #e5e7eb; font-size:14px; }}
        th {{ color:#64748b; letter-spacing:.08em; text-transform:uppercase; font-size:12px; }}
        .pill {{ color:white; padding:7px 11px; border-radius:999px; font-weight:800; font-size:12px; }}
        a {{ color:#1d4ed8; font-weight:700; }}
        .small {{ color:#64748b; font-size:13px; margin-top:18px; }}
      </style>
    </head>
    <body>
      <h1>V25 — Remote Snapshot Store Dashboard</h1>
      <div class="hero">
        <h2>Fuente única maestra activa</h2>
        <p>Consolida snapshot local de IBKR + opciones + técnico + decisión en un solo archivo remoto.</p>
        <p>Generado: {_v25_html_escape(_v25_now_iso())}</p>
      </div>
      <div class="grid">
        <div class="card"><div>Master snapshot</div><div class="num">{'Sí' if bool(master) else 'No'}</div></div>
        <div class="card"><div>Rows encontradas</div><div class="num">{len(rows)}</div></div>
        <div class="card"><div>Technical disponible</div><div class="num">{'Sí' if bool(technical) else 'No'}</div></div>
        <div class="card"><div>Tickers detectados</div><div class="num">{len(tickers)}</div></div>
      </div>
      <table>
        <thead>
          <tr>
            <th>Ticker</th>
            <th>Estado</th>
            <th>Estrategia</th>
            <th>Técnico</th>
            <th>Rows</th>
            <th>Operable</th>
            <th>Bloqueador</th>
            <th>Acción</th>
          </tr>
        </thead>
        <tbody>{rows_html}</tbody>
      </table>
      <p class="small">Endpoints: /v25_system_status · /v25_trade_decision/QQQ · /v25_dashboard/QQQ · POST /v25_ingest_snapshot</p>
    </body>
    </html>
    """
    return HTMLResponse(html)


@app.get("/v25_dashboard/{ticker}")
async def v25_dashboard_ticker(ticker: str):
    d = _v25_make_decision(ticker)
    sev = d.get("severity", "gray")
    color = {"green": "#16a34a", "yellow": "#ca8a04", "red": "#dc2626", "gray": "#64748b"}.get(sev, "#64748b")

    best = d.get("best_row") or {}
    tech = d.get("technical") or {}

    html = f"""
    <html>
    <head>
      <title>V25 {ticker}</title>
      <style>
        body {{ font-family: Inter, Arial, sans-serif; background:#f5f7fb; color:#0f172a; margin:0; padding:32px; }}
        h1 {{ font-size:34px; }}
        .hero {{ background:#0f172a; color:white; border-radius:26px; padding:34px; margin-bottom:24px; }}
        .pill {{ display:inline-block; color:white; background:{color}; padding:8px 14px; border-radius:999px; font-weight:800; }}
        .grid {{ display:grid; grid-template-columns:1fr 1fr; gap:18px; }}
        .card {{ background:white; border-radius:18px; padding:22px; box-shadow:0 12px 30px rgba(15,23,42,.08); }}
        pre {{ white-space:pre-wrap; background:#0f172a; color:white; padding:18px; border-radius:14px; overflow:auto; }}
        a {{ color:#1d4ed8; font-weight:700; }}
      </style>
    </head>
    <body>
      <h1>V25 — {_v25_html_escape(ticker)}</h1>
      <div class="hero">
        <div class="pill">{_v25_html_escape(d.get('final_state'))}</div>
        <h2>{_v25_html_escape(d.get('decision'))}</h2>
        <p>{_v25_html_escape(d.get('action'))}</p>
      </div>
      <div class="grid">
        <div class="card">
          <h3>Resumen</h3>
          <p><b>Can operate:</b> {'Sí' if d.get('can_operate') else 'No'}</p>
          <p><b>Estrategia:</b> {_v25_html_escape(d.get('strategy'))}</p>
          <p><b>Technical fit:</b> {_v25_html_escape(d.get('technical_fit'))}</p>
          <p><b>Rows ticker:</b> {_v25_html_escape(d.get('rows_found_for_ticker'))}</p>
          <p><b>Bloqueador:</b> {_v25_html_escape(d.get('main_blocker'))}</p>
        </div>
        <div class="card">
          <h3>Técnico</h3>
          <pre>{_v25_html_escape(_v25_json.dumps(tech, ensure_ascii=False, indent=2, default=str))}</pre>
        </div>
      </div>
      <div class="card" style="margin-top:18px;">
        <h3>Best Row</h3>
        <pre>{_v25_html_escape(_v25_json.dumps(best, ensure_ascii=False, indent=2, default=str))}</pre>
      </div>
      <p><a href="/v25_dashboard">Volver al dashboard V25</a></p>
    </body>
    </html>
    """
    return HTMLResponse(html)

# === END V25 REMOTE SNAPSHOT STORE / UNIFIED INGEST ===
'''

if "V25 REMOTE SNAPSHOT STORE / UNIFIED INGEST" in s:
    print("V25 block already exists. No duplicate inserted.")
else:
    s = s.rstrip() + "\n\n" + block + "\n"
    p.write_text(s)
    print("V25 Remote Snapshot Store patch applied.")
