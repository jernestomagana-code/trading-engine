from pathlib import Path

APP = Path("app/main.py")
s = APP.read_text()

backup = Path("app/main_backup_before_v27_1_runtime_data_resolver.py")
backup.write_text(s)

block = r'''

# ============================================================
# V27.1 RUNTIME DATA RESOLVER HOTFIX
# ============================================================
from pathlib import Path as _V271Path
from datetime import datetime as _V271DateTime, timezone as _V271Timezone
import json as _v271_json
from fastapi.responses import HTMLResponse as _V271HTMLResponse

_V271_RUNTIME_DIR = _V271Path("runtime")

_V271_CANDIDATE_FILES = [
    "v25_master_snapshot.json",
    "v26_master_snapshot.json",
    "v22_2_unified_remote_snapshot.json",
    "v22_1_trade_decision.json",
    "v22_trade_decision.json",
    "decision_desk_snapshot.json",
    "decision_snapshot.json",
    "v18_decision_snapshot.json",
    "v18_decision_desk_snapshot.json",
    "technical_snapshot_by_ticker_safe.json",
    "technical_snapshot_by_ticker.json",
]

def _v271_now():
    return _V271DateTime.now(_V271Timezone.utc).isoformat()

def _v271_load_json(path):
    try:
        p = _V271Path(path)
        if not p.exists():
            return None, f"missing:{p}"
        return _v271_json.loads(p.read_text()), None
    except Exception as e:
        return None, str(e)

def _v271_runtime_inventory_payload():
    files = []
    discovered = []

    try:
        _V271_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        for p in sorted(_V271_RUNTIME_DIR.glob("*.json")):
            discovered.append(str(p))
    except Exception:
        pass

    candidate_paths = []
    for name in _V271_CANDIDATE_FILES:
        candidate_paths.append(_V271_RUNTIME_DIR / name)

    for p in sorted(set(candidate_paths + [_V271Path(x) for x in discovered]), key=lambda x: str(x)):
        data, err = _v271_load_json(p)
        item = {
            "path": str(p),
            "exists": p.exists(),
            "error": err,
            "type": type(data).__name__ if data is not None else None,
            "keys": [],
            "rows_like": 0,
            "ticker_like": [],
            "usable_score": 0,
        }

        if isinstance(data, dict):
            item["keys"] = list(data.keys())[:80]

            rows_like = 0
            for k in ["rows", "top", "top_5", "options_rows", "sample_rows", "best_rows"]:
                if isinstance(data.get(k), list):
                    rows_like += len(data.get(k) or [])

            if isinstance(data.get("options"), dict):
                for k in ["rows", "top", "top_5", "options_rows", "sample_rows", "best_rows"]:
                    if isinstance(data["options"].get(k), list):
                        rows_like += len(data["options"].get(k) or [])

            item["rows_like"] = rows_like

            tickers = set()
            for k in ["ticker", "tickers", "tickers_detected", "technical_tickers", "available_tickers"]:
                v = data.get(k)
                if isinstance(v, str):
                    tickers.add(v.upper())
                elif isinstance(v, list):
                    for x in v:
                        if isinstance(x, str):
                            tickers.add(x.upper())

            item["ticker_like"] = sorted(list(tickers))[:30]

            score = 0
            if rows_like:
                score += 50
            if "best_row" in data or "best" in data or "next_best_action" in data:
                score += 20
            if "technical" in data or "technical_snapshot" in data or "snapshot" in data:
                score += 20
            if "market_hours" in data or "market" in data:
                score += 10
            if "ticker" in data:
                score += 10
            item["usable_score"] = score

        elif isinstance(data, list):
            item["rows_like"] = len(data)
            item["usable_score"] = 30 if len(data) else 0

        files.append(item)

    best = sorted(files, key=lambda x: x.get("usable_score", 0), reverse=True)
    return {
        "engine": "V27_1_RUNTIME_DATA_RESOLVER",
        "generated_at": _v271_now(),
        "status": "OK",
        "runtime_dir": str(_V271_RUNTIME_DIR),
        "files": files,
        "best_candidates": best[:10],
    }

def _v271_find_best_runtime_snapshot():
    inv = _v271_runtime_inventory_payload()
    candidates = inv.get("best_candidates", [])

    for item in candidates:
        if not item.get("exists"):
            continue
        if item.get("usable_score", 0) <= 0:
            continue
        data, err = _v271_load_json(item.get("path"))
        if data is not None:
            return data, item, inv

    return {}, None, inv

def _v271_rows_from_anywhere(data):
    rows = []

    def add_rows(x):
        if isinstance(x, list):
            for r in x:
                if isinstance(r, dict):
                    rows.append(dict(r))

    if isinstance(data, list):
        add_rows(data)

    if isinstance(data, dict):
        for k in ["rows", "top", "top_5", "options_rows", "sample_rows", "best_rows"]:
            add_rows(data.get(k))

        if isinstance(data.get("options"), dict):
            opt = data.get("options")
            for k in ["rows", "top", "top_5", "options_rows", "sample_rows", "best_rows"]:
                add_rows(opt.get(k))

        for k in ["best_row", "best", "next_best_action", "best_fusion_opportunity"]:
            v = data.get(k)
            if isinstance(v, dict):
                rows.append(dict(v))

        # Some decision objects have one ticker/strategy/decision at top level.
        if any(k in data for k in ["ticker", "strategy", "decision", "final_state", "can_operate"]):
            rows.append(dict(data))

    cleaned = []
    seen = set()
    for r in rows:
        t = None
        try:
            t = _v27_normalize_ticker(r.get("ticker"))
        except Exception:
            t = str(r.get("ticker") or "").upper().strip()

        if not t:
            continue

        if "strategy" not in r:
            r["strategy"] = r.get("best_strategy") or r.get("strategy_hint") or r.get("options_strategy") or "UNKNOWN"

        if "decision" not in r:
            r["decision"] = r.get("final_decision") or r.get("final_state") or r.get("state") or "RADAR"

        if "score" not in r:
            r["score"] = r.get("combined_score") or r.get("master_score") or r.get("options_score")

        if "data_quality" not in r:
            r["data_quality"] = r.get("quality") or r.get("option_quality") or "UNKNOWN"

        r["ticker"] = t

        key = (
            r.get("ticker"),
            str(r.get("strategy")),
            str(r.get("decision")),
            str(r.get("price") or r.get("premium") or r.get("option_price")),
        )
        if key not in seen:
            seen.add(key)
            cleaned.append(r)

    return cleaned

def _v271_technical_from_anywhere(data):
    technical = {}

    def ingest_obj(obj, forced_ticker=None):
        if not isinstance(obj, dict):
            return
        candidate = dict(obj)
        if forced_ticker and "ticker" not in candidate:
            candidate["ticker"] = forced_ticker
        try:
            cand = _v27_extract_technical_candidate(candidate)
        except Exception:
            cand = None
        if cand and cand.get("ticker"):
            technical[cand["ticker"]] = cand

    def walk(x):
        if isinstance(x, dict):
            # dict keyed by ticker
            for k, v in x.items():
                kt = None
                try:
                    kt = _v27_normalize_ticker(k)
                except Exception:
                    kt = str(k).upper().strip()
                if isinstance(v, dict):
                    ingest_obj(v, kt)
                    walk(v)
                elif isinstance(v, list):
                    walk(v)

            for k in ["technical", "technical_snapshot", "snapshot", "raw"]:
                if isinstance(x.get(k), dict):
                    ingest_obj(x.get(k))
                    walk(x.get(k))

            ingest_obj(x)

        elif isinstance(x, list):
            for item in x:
                walk(item)

    walk(data)
    return technical

def _v271_market_from_anywhere(data):
    if isinstance(data, dict):
        try:
            return _v27_market_hours(data)
        except Exception:
            pass

        mh = data.get("market_hours") or data.get("market") or {}
        if isinstance(mh, dict):
            return {
                "label": mh.get("label") or mh.get("market_hours_label") or "UNKNOWN",
                "is_regular_market_open": bool(mh.get("is_regular_market_open", False) or mh.get("is_open", False)),
                "options_bidask_expected": bool(mh.get("options_bidask_expected", False)),
                "raw": mh,
            }

    return {
        "label": "UNKNOWN",
        "is_regular_market_open": False,
        "options_bidask_expected": False,
        "raw": {},
    }

def _v271_decide_for_ticker(ticker):
    ticker = _v27_normalize_ticker(ticker)
    data, source_item, inv = _v271_find_best_runtime_snapshot()

    rows = _v271_rows_from_anywhere(data)
    technical_map = _v271_technical_from_anywhere(data)

    # Also merge V27 technical file resolver.
    try:
        tech2, diag2 = _v27_load_technical_map()
        for k, v in tech2.items():
            technical_map.setdefault(k, v)
    except Exception:
        diag2 = []

    market = _v271_market_from_anywhere(data)

    best_row = None
    try:
        best_row = _v27_choose_best_option_row(ticker, rows)
    except Exception:
        filtered = [r for r in rows if str(r.get("ticker")).upper() == ticker]
        best_row = filtered[0] if filtered else None

    technical = technical_map.get(ticker)

    if not best_row and not technical:
        return {
            "engine": "V27_1_RUNTIME_DATA_RESOLVER",
            "generated_at": _v271_now(),
            "ticker": ticker,
            "status": "OK",
            "final_state": "NO_DATA",
            "decision": "NO_DATA",
            "can_operate": False,
            "severity": "red",
            "main_blocker": "NO_OPTIONS_OR_TECHNICAL_DATA",
            "action": f"{ticker}: no hay datos técnicos ni opciones disponibles en runtime.",
            "executive_summary": f"{ticker}: V27.1 no encontró filas ni técnico utilizable.",
            "strategy": "UNKNOWN",
            "technical_bias": "UNKNOWN",
            "technical_score": None,
            "options_score": None,
            "best_row": {},
            "technical": {},
            "rows_found_for_ticker": 0,
            "total_rows_found": len(rows),
            "runtime_source": source_item,
            "inventory_summary": inv.get("best_candidates", [])[:5],
        }

    if not best_row:
        return {
            "engine": "V27_1_RUNTIME_DATA_RESOLVER",
            "generated_at": _v271_now(),
            "ticker": ticker,
            "status": "OK",
            "final_state": "WAIT_OPTIONS_DATA",
            "decision": "WAIT_OPTIONS_DATA",
            "can_operate": False,
            "severity": "yellow",
            "main_blocker": "NO_OPTIONS_ROW_FOR_TICKER",
            "action": f"{ticker}: técnico disponible, pero falta fila de opciones.",
            "executive_summary": f"{ticker}: técnico disponible sin oportunidad de opciones.",
            "strategy": "UNKNOWN",
            "technical_bias": technical.get("trend", "UNKNOWN") if technical else "UNKNOWN",
            "technical_score": technical.get("score") if technical else None,
            "options_score": None,
            "best_row": {},
            "technical": technical or {},
            "rows_found_for_ticker": 0,
            "total_rows_found": len(rows),
            "runtime_source": source_item,
        }

    strategy = str(best_row.get("strategy") or best_row.get("strategy_hint") or "UNKNOWN").upper()

    try:
        option_ok, option_reason = _v27_row_operable(best_row)
    except Exception:
        option_ok, option_reason = bool(best_row.get("can_operate")), "OPTIONS_EVALUATED"

    try:
        technical_ok, technical_reason = _v27_technical_confirmed_for_strategy(strategy, technical)
    except Exception:
        technical_ok, technical_reason = bool(technical), "TECHNICAL_EVALUATED"

    market_open = bool(market.get("is_regular_market_open"))
    bidask_expected = bool(market.get("options_bidask_expected"))
    market_ok = market_open and bidask_expected

    if option_ok and technical_ok and market_ok:
        final_state = "ENTRY_READY"
        decision = "ENTRY_READY"
        severity = "green"
        blocker = None
        action = f"{ticker}: posible entrada. Validar tamaño, spread, liquidez y riesgo final antes de ejecutar."
    elif option_ok and technical_ok and not market_ok:
        final_state = "WAIT_MARKET_OPEN"
        decision = "WAIT_MARKET_OPEN"
        severity = "gray"
        blocker = "MARKET_OR_OPTIONS_WINDOW_NOT_RELIABLE"
        action = f"{ticker}: setup válido, pero esperar ventana confiable de mercado/opciones."
    elif option_ok and not technical_ok:
        final_state = "WAIT_TECHNICAL_CONFIRMATION"
        decision = "WAIT_TECHNICAL_CONFIRMATION"
        severity = "yellow"
        blocker = technical_reason
        action = f"{ticker}: opciones operables, pero falta confirmación técnica para {strategy}."
    elif not option_ok and technical_ok:
        final_state = "WAIT_OPTIONS_DATA"
        decision = "WAIT_OPTIONS_DATA"
        severity = "yellow"
        blocker = option_reason
        action = f"{ticker}: técnico confirmado, pero faltan datos/confirmaciones de opciones."
    else:
        final_state = "WAIT_DATA_CONFIRMATION"
        decision = "WAIT_DATA_CONFIRMATION"
        severity = "yellow"
        blocker = f"{option_reason}+{technical_reason}"
        action = f"{ticker}: faltan confirmaciones técnicas y/o de opciones."

    return {
        "engine": "V27_1_RUNTIME_DATA_RESOLVER",
        "generated_at": _v271_now(),
        "ticker": ticker,
        "status": "OK",
        "final_state": final_state,
        "decision": decision,
        "can_operate": final_state == "ENTRY_READY",
        "severity": severity,
        "main_blocker": blocker,
        "action": action,
        "executive_summary": (
            f"{ticker}: estado {final_state}. Estrategia {strategy}. "
            f"Opciones: {option_reason}. Técnico: {technical_reason}. Acción: {action}"
        ),
        "strategy": strategy,
        "technical_bias": (technical or {}).get("trend", "UNKNOWN"),
        "technical_score": (technical or {}).get("score"),
        "options_score": best_row.get("score") or best_row.get("combined_score") or best_row.get("master_score"),
        "options_fit": option_reason,
        "technical_fit": technical_reason,
        "best_row": best_row,
        "technical": technical or {},
        "rows_found_for_ticker": len([r for r in rows if r.get("ticker") == ticker]),
        "total_rows_found": len(rows),
        "market": market,
        "runtime_source": source_item,
    }

def _v271_dashboard_html(tickers=None):
    if not tickers:
        tickers = ["QQQ", "SPY", "NVDA", "TSLA", "META", "TLT"]

    decisions = [_v271_decide_for_ticker(t) for t in tickers]
    entry_count = sum(1 for d in decisions if d.get("final_state") == "ENTRY_READY")
    wait_tech = sum(1 for d in decisions if d.get("final_state") == "WAIT_TECHNICAL_CONFIRMATION")
    wait_options = sum(1 for d in decisions if d.get("final_state") == "WAIT_OPTIONS_DATA")
    wait_data = sum(1 for d in decisions if d.get("final_state") in {"NO_DATA", "WAIT_DATA_CONFIRMATION"})

    rows = ""
    for d in decisions:
        state = d.get("final_state")
        color = _v27_badge_color(state)
        ticker = d.get("ticker")
        rows += f"""
        <tr>
          <td><a href="/v27_1_trade_decision/{_v27_html_escape(ticker)}">{_v27_html_escape(ticker)}</a></td>
          <td><span class="badge" style="background:{color};">{_v27_html_escape(state)}</span></td>
          <td>{_v27_html_escape(d.get("strategy"))}</td>
          <td>{_v27_html_escape(d.get("technical_bias"))}</td>
          <td>{_v27_html_escape(d.get("technical_score"))}</td>
          <td>{_v27_html_escape(d.get("options_score"))}</td>
          <td>{'Sí' if d.get("can_operate") else 'No'}</td>
          <td>{_v27_html_escape(d.get("main_blocker"))}</td>
          <td>{_v27_html_escape(d.get("action"))}</td>
        </tr>
        """

    html = f"""
    <!doctype html>
    <html>
    <head>
      <meta charset="utf-8">
      <title>V27.1 Runtime Data Resolver Dashboard</title>
      <style>
        body {{
          margin:0;
          padding:36px;
          background:#f4f6fa;
          color:#0f172a;
          font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;
        }}
        h1 {{ font-size:34px; margin:0 0 22px; }}
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
        .card .label {{ color:#64748b; font-weight:700; font-size:13px; text-transform:uppercase; letter-spacing:.06em; }}
        .card .value {{ font-size:32px; font-weight:800; margin-top:8px; }}
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
          font-weight:800;
        }}
        .footer {{
          margin-top:20px;
          color:#64748b;
          font-size:13px;
        }}
        a {{ color:#2563eb; font-weight:700; }}
      </style>
    </head>
    <body>
      <h1>V27.1 — Runtime Data Resolver Dashboard</h1>
      <div class="hero">
        <h2>Execution Guard activo</h2>
        <p>Busca automáticamente snapshots runtime y consolida técnico + opciones + mercado.</p>
        <p>Generado: {_v27_html_escape(_v271_now())}</p>
      </div>

      <div class="cards">
        <div class="card"><div class="label">Entry Ready</div><div class="value">{entry_count}</div></div>
        <div class="card"><div class="label">Wait Technical</div><div class="value">{wait_tech}</div></div>
        <div class="card"><div class="label">Wait Options</div><div class="value">{wait_options}</div></div>
        <div class="card"><div class="label">Wait Data</div><div class="value">{wait_data}</div></div>
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
        <tbody>{rows}</tbody>
      </table>

      <div class="footer">
        Endpoints: /v27_1_runtime_inventory · /v27_1_system_status · /v27_1_trade_decision/QQQ · /v27_1_dashboard
      </div>
    </body>
    </html>
    """
    return html

@app.get("/v27_1_runtime_inventory")
async def v27_1_runtime_inventory():
    return _v271_runtime_inventory_payload()

@app.get("/v27_1_system_status")
async def v27_1_system_status():
    data, source_item, inv = _v271_find_best_runtime_snapshot()
    rows = _v271_rows_from_anywhere(data)
    technical = _v271_technical_from_anywhere(data)
    detected = sorted(list(set([r.get("ticker") for r in rows if r.get("ticker")] + list(technical.keys()))))
    return {
        "engine": "V27_1_RUNTIME_DATA_RESOLVER",
        "generated_at": _v271_now(),
        "status": "OK",
        "best_runtime_source": source_item,
        "rows_found": len(rows),
        "technical_available": bool(technical),
        "technical_tickers": sorted(list(technical.keys())),
        "tickers_detected": detected,
        "market": _v271_market_from_anywhere(data),
        "endpoints": {
            "runtime_inventory": "/v27_1_runtime_inventory",
            "trade_decision_example": "/v27_1_trade_decision/QQQ",
            "dashboard": "/v27_1_dashboard",
            "dashboard_ticker_example": "/v27_1_dashboard/QQQ",
        },
        "inventory_best_candidates": inv.get("best_candidates", [])[:10],
    }

@app.get("/v27_1_trade_decision/{ticker}")
async def v27_1_trade_decision(ticker: str):
    return _v271_decide_for_ticker(ticker)

@app.get("/gpt_v27_1_trade_decision/{ticker}")
async def gpt_v27_1_trade_decision(ticker: str):
    d = _v271_decide_for_ticker(ticker)
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
        "risk_note": "No ejecutar sin validar manualmente tamaño, liquidez, spread, evento, capital y tolerancia de riesgo.",
        "runtime_source": d.get("runtime_source"),
        "engine": d.get("engine"),
        "generated_at": d.get("generated_at"),
    }

@app.get("/v27_1_dashboard", response_class=_V271HTMLResponse)
async def v27_1_dashboard():
    return _v271_dashboard_html()

@app.get("/v27_1_dashboard/{ticker}", response_class=_V271HTMLResponse)
async def v27_1_dashboard_ticker(ticker: str):
    return _v271_dashboard_html([ticker])

# ============================================================
# END V27.1 RUNTIME DATA RESOLVER HOTFIX
# ============================================================
'''

marker = "# ============================================================\n# V27.1 RUNTIME DATA RESOLVER HOTFIX\n# ============================================================"

if marker in s:
    print("V27.1 block already exists. No duplicate inserted.")
else:
    s = s.rstrip() + "\n\n" + block + "\n"
    APP.write_text(s)
    print("V27.1 runtime data resolver patch applied.")

