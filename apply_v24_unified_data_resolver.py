from pathlib import Path

p = Path("app/main.py")
s = p.read_text()

backup = Path("app/main_backup_before_v24_unified_data_resolver.py")
backup.write_text(s)

marker = "# === V24 UNIFIED DATA RESOLVER ==="

v24_block = r'''

# === V24 UNIFIED DATA RESOLVER ===
from pathlib import Path as _V24Path
from datetime import datetime as _V24DateTime, timezone as _V24Timezone
import json as _v24_json

_V24_RUNTIME = _V24Path("runtime")
_V24_RUNTIME.mkdir(exist_ok=True)

_V24_DECISION_FILES = [
    _V24Path("runtime/v22_2_unified_remote_snapshot.json"),
    _V24Path("runtime/v22_unified_remote_snapshot.json"),
    _V24Path("runtime/decision_desk_snapshot.json"),
    _V24Path("runtime/decision_snapshot.json"),
    _V24Path("runtime/v18_decision_desk_snapshot.json"),
    _V24Path("runtime/v18_decision_snapshot.json"),
    _V24Path("decision_desk_snapshot.json"),
    _V24Path("decision_snapshot.json"),
]

_V24_TECHNICAL_FILES = [
    _V24Path("runtime/technical_snapshot_by_ticker_safe.json"),
    _V24Path("runtime/technical_snapshot_by_ticker.json"),
    _V24Path("technical_snapshot_by_ticker_safe.json"),
    _V24Path("technical_snapshot_by_ticker.json"),
]

def _v24_now():
    return _V24DateTime.now(_V24Timezone.utc).isoformat()

def _v24_load_json(path):
    try:
        if not path.exists():
            return None
        txt = path.read_text().strip()
        if not txt:
            return None
        return _v24_json.loads(txt)
    except Exception:
        return None

def _v24_as_list(x):
    if x is None:
        return []
    if isinstance(x, list):
        return x
    return [x]

def _v24_norm_ticker(t):
    return str(t or "").upper().strip()

def _v24_find_rows(obj):
    rows = []
    if obj is None:
        return rows

    if isinstance(obj, list):
        return obj

    if not isinstance(obj, dict):
        return rows

    candidate_keys = [
        "rows",
        "top",
        "top_5",
        "opportunities",
        "items",
        "data",
        "records",
        "decision_rows",
    ]

    for k in candidate_keys:
        v = obj.get(k)
        if isinstance(v, list):
            rows.extend(v)

    for k in ["best", "best_row", "best_opportunity", "next_best_action"]:
        v = obj.get(k)
        if isinstance(v, dict):
            rows.append(v)

    by_ticker = obj.get("by_ticker")
    if isinstance(by_ticker, dict):
        for _, v in by_ticker.items():
            if isinstance(v, dict):
                if isinstance(v.get("rows"), list):
                    rows.extend(v.get("rows"))
                if isinstance(v.get("best"), dict):
                    rows.append(v.get("best"))
                else:
                    rows.append(v)
            elif isinstance(v, list):
                rows.extend(v)

    summary = obj.get("summary")
    if isinstance(summary, dict):
        rows.extend(_v24_find_rows(summary))

    return [r for r in rows if isinstance(r, dict)]

def _v24_extract_ticker(row):
    return _v24_norm_ticker(
        row.get("ticker")
        or row.get("symbol")
        or row.get("underlying")
        or row.get("underlying_symbol")
        or row.get("option_symbol")
    )

def _v24_extract_strategy(row):
    return str(
        row.get("strategy")
        or row.get("strategy_hint")
        or row.get("best_strategy")
        or row.get("primary_focus")
        or row.get("setup")
        or "UNKNOWN"
    ).upper()

def _v24_extract_score(row):
    for k in ["combined_score", "score", "master_score", "technical_score", "options_score"]:
        try:
            v = row.get(k)
            if v is not None:
                return float(v)
        except Exception:
            pass
    return None

def _v24_pick_best_row(rows, ticker=None):
    ticker = _v24_norm_ticker(ticker)
    filtered = []
    for r in rows:
        if ticker and _v24_extract_ticker(r) != ticker:
            continue
        filtered.append(r)

    if not filtered:
        return None

    def sort_key(r):
        can = bool(r.get("can_operate") or r.get("can_trade"))
        decision = str(r.get("decision") or r.get("final_decision") or r.get("state") or "").upper()
        entry_bonus = 1000 if ("ENTRY" in decision or can) else 0
        score = _v24_extract_score(r) or 0
        return entry_bonus + score

    return sorted(filtered, key=sort_key, reverse=True)[0]

def _v24_load_decision_context(ticker=None):
    all_rows = []
    files_seen = []
    raw_sources = []

    for f in _V24_DECISION_FILES:
        obj = _v24_load_json(f)
        if obj is not None:
            files_seen.append(str(f))
            raw_sources.append({"file": str(f), "type": type(obj).__name__})
            all_rows.extend(_v24_find_rows(obj))

    best = _v24_pick_best_row(all_rows, ticker)

    return {
        "available": bool(all_rows),
        "rows_found": len(all_rows),
        "files_seen": files_seen,
        "sources": raw_sources,
        "best_row": best,
        "rows": all_rows[:100],
    }

def _v24_load_technical_context(ticker=None):
    ticker = _v24_norm_ticker(ticker)
    files_seen = []
    available_tickers = []
    snapshot = None

    for f in _V24_TECHNICAL_FILES:
        obj = _v24_load_json(f)
        if obj is None:
            continue

        files_seen.append(str(f))

        if isinstance(obj, dict):
            if ticker and ticker in obj and isinstance(obj.get(ticker), dict):
                snapshot = obj.get(ticker)
                available_tickers = list(obj.keys())
                break

            if ticker and _v24_norm_ticker(obj.get("ticker")) == ticker:
                snapshot = obj
                available_tickers = [ticker]
                break

            for k, v in obj.items():
                if isinstance(v, dict):
                    available_tickers.append(str(k).upper())

    return {
        "available": snapshot is not None,
        "ticker": ticker,
        "snapshot": snapshot,
        "available_tickers": sorted(list(set(available_tickers))),
        "files_seen": files_seen,
    }

def _v24_market_context():
    try:
        mh = globals().get("market_hours", None)
        if callable(mh):
            return mh()
    except Exception:
        pass

    return {
        "status": "UNKNOWN",
        "label": "Market hours unknown",
        "is_regular_market_open": None,
        "options_bidask_expected": None,
        "new_york_time": None,
        "next_check": "Validate market hours manually.",
    }

def _v24_get_value(d, *keys, default=None):
    if not isinstance(d, dict):
        return default
    for k in keys:
        if d.get(k) is not None:
            return d.get(k)
    return default

def _v24_decision_for_ticker(ticker):
    ticker = _v24_norm_ticker(ticker)
    decision_ctx = _v24_load_decision_context(ticker)
    technical_ctx = _v24_load_technical_context(ticker)
    market_ctx = _v24_market_context()

    row = decision_ctx.get("best_row") or {}

    strategy = _v24_extract_strategy(row)
    score = _v24_extract_score(row)
    technical = technical_ctx.get("snapshot") or {}

    tech_bias = str(
        _v24_get_value(
            technical,
            "bias",
            "trend",
            "technical_bias",
            default="UNKNOWN"
        )
    ).upper()

    tech_score = _v24_get_value(technical, "score", "technical_score", default=None)

    options_available = bool(decision_ctx.get("rows_found", 0) > 0)
    technical_available = bool(technical_ctx.get("available"))

    market_status = str((market_ctx or {}).get("status") or "UNKNOWN").upper()
    options_bidask_expected = bool((market_ctx or {}).get("options_bidask_expected"))

    row_can_operate = bool(row.get("can_operate") or row.get("can_trade"))

    decision_text = str(
        row.get("decision")
        or row.get("final_decision")
        or row.get("state")
        or ""
    ).upper()

    if not options_available and not technical_available:
        final_state = "NO_DATA"
        can_operate = False
        main_blocker = "NO_TECHNICAL_OR_OPTIONS_DATA"
        action = f"{ticker}: no hay datos técnicos ni datos de opciones disponibles todavía."
        severity = "red"
    elif not technical_available:
        final_state = "WAIT_TECHNICAL_DATA"
        can_operate = False
        main_blocker = "NO_TECHNICAL_SNAPSHOT"
        action = f"{ticker}: no operar todavía. Falta snapshot técnico para confirmar dirección y contexto."
        severity = "gray"
    elif not options_available:
        final_state = "WAIT_OPTIONS_DATA"
        can_operate = False
        main_blocker = "NO_OPTIONS_ROWS"
        action = f"{ticker}: no operar todavía. Hay técnico disponible, pero faltan filas de opciones."
        severity = "gray"
    elif market_status != "REGULAR_OPTIONS_SESSION" and not options_bidask_expected:
        final_state = "WAIT_MARKET_OPEN"
        can_operate = False
        main_blocker = "OPTIONS_MARKET_NOT_RELIABLE"
        action = "No operar ahora. Esperar ventana confiable de mercado/opciones. Revisar después de 09:35 ET."
        severity = "gray"
    elif row_can_operate or "ENTRY" in decision_text:
        final_state = "ENTRY_READY"
        can_operate = True
        main_blocker = None
        action = "Entrada potencial lista. Validar tamaño, riesgo, spread y confirmación final antes de ejecutar."
        severity = "green"
    else:
        final_state = "RADAR"
        can_operate = False
        main_blocker = "NOT_FULLY_CONFIRMED"
        action = "Mantener en radar. Faltan confirmaciones para entrada operable."
        severity = "yellow"

    return {
        "engine": "V24_UNIFIED_DATA_RESOLVER",
        "generated_at": _v24_now(),
        "ticker": ticker,
        "status": "OK",
        "final_state": final_state,
        "decision": final_state,
        "can_operate": can_operate,
        "severity": severity,
        "main_blocker": main_blocker,
        "action": action,
        "strategy": strategy,
        "score": score,
        "technical": {
            "available": technical_available,
            "bias": tech_bias,
            "score": tech_score,
            "snapshot": technical,
            "available_tickers": technical_ctx.get("available_tickers", []),
        },
        "options": {
            "available": options_available,
            "rows_found": decision_ctx.get("rows_found", 0),
            "best_row": row,
            "sample_rows": decision_ctx.get("rows", [])[:10],
        },
        "market_hours": market_ctx,
        "diagnostics": {
            "decision_files_seen": decision_ctx.get("files_seen", []),
            "technical_files_seen": technical_ctx.get("files_seen", []),
        },
    }

@app.get("/v24_trade_decision/{ticker}")
async def v24_trade_decision(ticker: str):
    return _v24_decision_for_ticker(ticker)

@app.get("/v24_system_status")
async def v24_system_status():
    tickers = set()
    decision_ctx = _v24_load_decision_context()
    tech_ctx = _v24_load_technical_context()

    for r in decision_ctx.get("rows", []):
        t = _v24_extract_ticker(r)
        if t:
            tickers.add(t)

    for t in tech_ctx.get("available_tickers", []):
        tickers.add(t)

    return {
        "engine": "V24_UNIFIED_DATA_RESOLVER",
        "generated_at": _v24_now(),
        "status": "OK",
        "decision_rows_found": decision_ctx.get("rows_found", 0),
        "technical_snapshot_available": tech_ctx.get("available", False),
        "technical_tickers": tech_ctx.get("available_tickers", []),
        "tickers_detected": sorted(list(tickers)),
        "market_hours": _v24_market_context(),
        "endpoints": {
            "v24_system_status": "/v24_system_status",
            "v24_trade_decision_example": "/v24_trade_decision/QQQ",
            "v24_dashboard": "/v24_dashboard",
            "v24_dashboard_ticker_example": "/v24_dashboard/QQQ",
        },
        "diagnostics": {
            "decision_files_seen": decision_ctx.get("files_seen", []),
            "technical_files_seen": tech_ctx.get("files_seen", []),
        },
    }

def _v24_html_escape(x):
    import html
    return html.escape(str(x if x is not None else ""))

def _v24_badge_color(state):
    s = str(state or "").upper()
    if "ENTRY" in s:
        return "#16a34a"
    if "RADAR" in s:
        return "#f59e0b"
    if "WAIT" in s:
        return "#64748b"
    if "NO_DATA" in s:
        return "#dc2626"
    return "#64748b"

def _v24_render_dashboard(ticker=None):
    status = _v24_system_status
    tlist = []
    system = {
        "tickers_detected": [],
        "decision_rows_found": 0,
        "technical_tickers": [],
    }

    try:
        decision_ctx = _v24_load_decision_context()
        tech_ctx = _v24_load_technical_context()
        for r in decision_ctx.get("rows", []):
            rt = _v24_extract_ticker(r)
            if rt:
                tlist.append(rt)
        tlist.extend(tech_ctx.get("available_tickers", []))
    except Exception:
        pass

    tickers = sorted(list(set(tlist)))
    if ticker:
        tickers = [_v24_norm_ticker(ticker)]

    if not tickers:
        tickers = ["QQQ"]

    rows_html = ""
    cards = []

    for t in tickers:
        d = _v24_decision_for_ticker(t)
        color = _v24_badge_color(d.get("final_state"))
        rows_html += f"""
        <tr>
            <td><a href="/v24_dashboard/{_v24_html_escape(t)}">{_v24_html_escape(t)}</a></td>
            <td><span class="badge" style="background:{color}">{_v24_html_escape(d.get("final_state"))}</span></td>
            <td>{_v24_html_escape(d.get("strategy"))}</td>
            <td>{_v24_html_escape(d.get("technical", {}).get("bias"))}</td>
            <td>{_v24_html_escape(d.get("score"))}</td>
            <td>{'Sí' if d.get("can_operate") else 'No'}</td>
            <td>{_v24_html_escape(d.get("action"))}</td>
        </tr>
        """
        cards.append(d)

    headline = "Execution Guard activo"
    if any(c.get("can_operate") for c in cards):
        headline = "Entrada potencial detectada"
    elif any(c.get("final_state") == "RADAR" for c in cards):
        headline = "Oportunidades en radar"

    generated = _v24_now()

    return f"""
    <!doctype html>
    <html>
    <head>
        <meta charset="utf-8"/>
        <meta name="viewport" content="width=device-width, initial-scale=1"/>
        <title>V24 Unified Data Resolver</title>
        <style>
            body {{
                font-family: Inter, Arial, sans-serif;
                background:#f6f7fb;
                color:#0f172a;
                padding:32px;
            }}
            h1 {{
                font-size:34px;
                margin-bottom:20px;
            }}
            .hero {{
                background:#0f172a;
                color:white;
                border-radius:24px;
                padding:36px;
                margin-bottom:24px;
            }}
            .hero h2 {{
                margin:0 0 14px 0;
                font-size:26px;
            }}
            .grid {{
                display:grid;
                grid-template-columns: repeat(4, 1fr);
                gap:16px;
                margin-bottom:24px;
            }}
            .card {{
                background:white;
                padding:22px;
                border-radius:18px;
                box-shadow:0 12px 28px rgba(15,23,42,.08);
            }}
            .card .num {{
                font-size:30px;
                font-weight:800;
            }}
            table {{
                width:100%;
                border-collapse:collapse;
                background:white;
                border-radius:18px;
                overflow:hidden;
                box-shadow:0 12px 28px rgba(15,23,42,.08);
            }}
            th, td {{
                text-align:left;
                padding:14px 16px;
                border-bottom:1px solid #e5e7eb;
                font-size:14px;
            }}
            th {{
                text-transform:uppercase;
                letter-spacing:.08em;
                font-size:12px;
                color:#64748b;
            }}
            .badge {{
                display:inline-block;
                color:white;
                padding:6px 10px;
                border-radius:999px;
                font-weight:800;
                font-size:12px;
            }}
            .footer {{
                margin-top:24px;
                color:#64748b;
                font-size:13px;
            }}
        </style>
    </head>
    <body>
        <h1>V24 — Unified Data Resolver</h1>
        <div class="hero">
            <h2>{_v24_html_escape(headline)}</h2>
            <p>Consolida datos técnicos, opciones, snapshots remotos y estado de mercado para evitar decisiones ciegas.</p>
            <p>Generado: {_v24_html_escape(generated)}</p>
        </div>

        <div class="grid">
            <div class="card"><div>Tickers detectados</div><div class="num">{len(tickers)}</div></div>
            <div class="card"><div>Technical disponibles</div><div class="num">{sum(1 for c in cards if c.get("technical", {}).get("available"))}</div></div>
            <div class="card"><div>Options disponibles</div><div class="num">{sum(1 for c in cards if c.get("options", {}).get("available"))}</div></div>
            <div class="card"><div>Operables</div><div class="num">{sum(1 for c in cards if c.get("can_operate"))}</div></div>
        </div>

        <table>
            <thead>
                <tr>
                    <th>Ticker</th>
                    <th>Estado</th>
                    <th>Estrategia</th>
                    <th>Sesgo técnico</th>
                    <th>Score</th>
                    <th>Operable</th>
                    <th>Acción</th>
                </tr>
            </thead>
            <tbody>
                {rows_html}
            </tbody>
        </table>

        <div class="footer">
            Endpoints: /v24_system_status · /v24_trade_decision/QQQ · /v24_dashboard · /v24_dashboard/QQQ
        </div>
    </body>
    </html>
    """

@app.get("/v24_dashboard")
async def v24_dashboard():
    from fastapi.responses import HTMLResponse
    return HTMLResponse(_v24_render_dashboard())

@app.get("/v24_dashboard/{ticker}")
async def v24_dashboard_ticker(ticker: str):
    from fastapi.responses import HTMLResponse
    return HTMLResponse(_v24_render_dashboard(ticker))

# === END V24 UNIFIED DATA RESOLVER ===
'''

if marker not in s:
    s = s.rstrip() + "\n\n" + v24_block + "\n"
else:
    print("V24 block already exists. No duplicate inserted.")

p.write_text(s)
print("V24 Unified Data Resolver patch applied.")
