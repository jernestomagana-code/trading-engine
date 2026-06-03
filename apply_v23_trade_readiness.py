from pathlib import Path

p = Path("app/main.py")
s = p.read_text()

backup = Path("app/main_backup_before_v23_trade_readiness.py")
backup.write_text(s)

block = r'''

# ============================================================
# V23 TRADE READINESS & EXECUTION GUARD
# ============================================================

from pathlib import Path as _V23Path
from datetime import datetime as _V23DateTime, timezone as _V23Timezone
import json as _v23_json

_V23_RUNTIME = _V23Path("runtime")
_V23_TECH_FILE = _V23_RUNTIME / "technical_snapshot_by_ticker_safe.json"
_V23_DECISION_FILE = _V23_RUNTIME / "decision_desk_snapshot.json"
_V23_UNIFIED_FILE = _V23_RUNTIME / "v22_2_unified_remote_snapshot.json"


def _v23_now():
    return _V23DateTime.now(_V23Timezone.utc).isoformat()


def _v23_read_json(path, default=None):
    try:
        path = _V23Path(path)
        if not path.exists():
            return default
        return _v23_json.loads(path.read_text())
    except Exception as e:
        return default


def _v23_get_technical_snapshot(ticker: str):
    ticker = (ticker or "").upper().strip()
    data = _v23_read_json(_V23_TECH_FILE, {})
    if not isinstance(data, dict):
        return None

    # soporta formato directo por ticker
    if ticker in data:
        return data.get(ticker)

    # soporta formato {"snapshots": {"QQQ": {...}}}
    snapshots = data.get("snapshots")
    if isinstance(snapshots, dict) and ticker in snapshots:
        return snapshots.get(ticker)

    # soporta formato de snapshot único
    if str(data.get("ticker", "")).upper() == ticker:
        return data

    return None


def _v23_get_decision_rows():
    data = _v23_read_json(_V23_DECISION_FILE, None)

    if data is None:
        data = _v23_read_json(_V23_UNIFIED_FILE, None)

    if not isinstance(data, dict):
        return [], None

    rows = data.get("rows")
    if isinstance(rows, list):
        return rows, data

    top = data.get("top")
    if isinstance(top, list):
        return top, data

    best = data.get("best") or data.get("best_row") or data.get("best_opportunity")
    if isinstance(best, dict):
        return [best], data

    return [], data


def _v23_find_best_option_row(ticker: str):
    ticker = (ticker or "").upper().strip()
    rows, raw = _v23_get_decision_rows()

    candidates = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        if str(r.get("ticker", "")).upper() != ticker:
            continue
        candidates.append(r)

    if not candidates:
        return None, rows, raw

    def score_row(r):
        try:
            return float(
                r.get("combined_score")
                or r.get("score")
                or r.get("options_score")
                or 0
            )
        except Exception:
            return 0

    candidates = sorted(candidates, key=score_row, reverse=True)
    return candidates[0], rows, raw


def _v23_market_context(raw_decision):
    if not isinstance(raw_decision, dict):
        return {
            "status": "UNKNOWN",
            "label": "Estado de mercado desconocido",
            "is_regular_market_open": False,
            "options_bidask_expected": False,
        }

    mh = raw_decision.get("market_hours") or {}
    if not isinstance(mh, dict):
        mh = {}

    return {
        "status": mh.get("status") or raw_decision.get("market_hours_status") or "UNKNOWN",
        "label": mh.get("label") or raw_decision.get("market_hours_label") or "Estado de mercado desconocido",
        "is_regular_market_open": bool(mh.get("is_regular_market_open") or raw_decision.get("is_regular_market_open")),
        "options_bidask_expected": bool(mh.get("options_bidask_expected") or raw_decision.get("options_bidask_expected")),
        "new_york_time": mh.get("new_york_time") or raw_decision.get("new_york_time"),
        "next_check": mh.get("next_check") or raw_decision.get("next_check"),
    }


def _v23_extract_technical_bias(tech):
    if not isinstance(tech, dict):
        return "UNKNOWN", None

    bias = (
        tech.get("bias")
        or tech.get("trend")
        or tech.get("technical_bias")
        or tech.get("direction")
        or "UNKNOWN"
    )

    score = tech.get("score") or tech.get("technical_score")

    try:
        score = float(score) if score is not None else None
    except Exception:
        score = None

    return str(bias).upper(), score


def _v23_extract_option_strategy(row):
    if not isinstance(row, dict):
        return "UNKNOWN", None

    strategy = (
        row.get("strategy")
        or row.get("best_strategy")
        or row.get("strategy_hint")
        or "UNKNOWN"
    )

    score = (
        row.get("combined_score")
        or row.get("score")
        or row.get("options_score")
    )

    try:
        score = float(score) if score is not None else None
    except Exception:
        score = None

    return str(strategy).upper(), score


def _v23_strategy_aligns(strategy, bias):
    strategy = (strategy or "").upper()
    bias = (bias or "").upper()

    if bias in ["UNKNOWN", "", "NONE"]:
        return None

    bullish_strategies = ["NAKED_PUT", "CASH_SECURED_PUT", "BULL_PUT", "PUT_CREDIT_SPREAD"]
    bearish_strategies = ["COVERED_CALL", "BEAR_CALL", "CALL_CREDIT_SPREAD"]

    if bias in ["BULLISH", "ALCISTA", "UP", "LONG"]:
        return strategy in bullish_strategies

    if bias in ["BEARISH", "BAJISTA", "DOWN", "SHORT"]:
        return strategy in bearish_strategies

    if bias in ["NEUTRAL", "RANGE", "SIDEWAYS"]:
        return strategy in bullish_strategies + bearish_strategies

    return None


def _v23_build_trade_readiness(ticker: str):
    ticker = (ticker or "").upper().strip()

    tech = _v23_get_technical_snapshot(ticker)
    best_row, rows, raw_decision = _v23_find_best_option_row(ticker)
    market = _v23_market_context(raw_decision)

    technical_available = isinstance(tech, dict)
    options_available = isinstance(best_row, dict)

    technical_bias, technical_score = _v23_extract_technical_bias(tech)
    strategy, options_score = _v23_extract_option_strategy(best_row)

    blockers = []
    warnings = []

    if not ticker:
        blockers.append("NO_TICKER")

    if not technical_available:
        blockers.append("NO_TECHNICAL_SNAPSHOT")

    if not options_available:
        blockers.append("NO_OPTIONS_ROW")

    if not market.get("is_regular_market_open"):
        blockers.append("MARKET_NOT_REGULAR_OPEN")

    if not market.get("options_bidask_expected"):
        blockers.append("OPTIONS_BIDASK_NOT_RELIABLE")

    if strategy == "UNKNOWN":
        warnings.append("Estrategia no identificada con claridad.")

    if technical_bias == "UNKNOWN":
        warnings.append("Sesgo técnico desconocido.")

    alignment = _v23_strategy_aligns(strategy, technical_bias)

    if alignment is False:
        blockers.append("TECHNICAL_STRATEGY_CONFLICT")

    if alignment is None:
        warnings.append("No se pudo validar alineación técnica de la estrategia.")

    row_can_operate = False
    if isinstance(best_row, dict):
        row_can_operate = bool(best_row.get("can_operate"))

    if options_available and not row_can_operate:
        row_missing = best_row.get("missing_confirmations") if isinstance(best_row, dict) else None
        if row_missing:
            warnings.append(f"Faltan confirmaciones: {row_missing}")

    can_operate = len(blockers) == 0 and technical_available and options_available

    if can_operate:
        final_state = "ENTRY_READY"
        decision = "ENTRY_READY"
        severity = "green"
        action = "Entrada candidata. Validar tamaño, riesgo, spread y confirmación final antes de ejecutar."
    else:
        if "MARKET_NOT_REGULAR_OPEN" in blockers or "OPTIONS_BIDASK_NOT_RELIABLE" in blockers:
            final_state = "WAIT_MARKET_OPEN"
            decision = "WAIT_MARKET_OPEN"
            severity = "gray"
            action = "No operar ahora. Esperar ventana confiable de mercado/opciones."
        elif "NO_TECHNICAL_SNAPSHOT" in blockers:
            final_state = "WAIT_TECHNICAL_DATA"
            decision = "WAIT_TECHNICAL_DATA"
            severity = "gray"
            action = "No operar todavía. Falta snapshot técnico."
        elif "NO_OPTIONS_ROW" in blockers:
            final_state = "WAIT_OPTIONS_DATA"
            decision = "WAIT_OPTIONS_DATA"
            severity = "gray"
            action = "No operar todavía. Falta oportunidad de opciones."
        elif "TECHNICAL_STRATEGY_CONFLICT" in blockers:
            final_state = "BLOCKED"
            decision = "BLOCKED"
            severity = "red"
            action = "No operar. Existe conflicto entre sesgo técnico y estrategia."
        else:
            final_state = "RADAR_ONLY"
            decision = "RADAR_ONLY"
            severity = "yellow"
            action = "Mantener en radar. Faltan validaciones para operar."

    return {
        "engine": "V23_TRADE_READINESS_EXECUTION_GUARD",
        "generated_at": _v23_now(),
        "ticker": ticker,
        "status": "OK",
        "final_state": final_state,
        "decision": decision,
        "can_operate": can_operate,
        "severity": severity,
        "strategy": strategy,
        "technical_bias": technical_bias,
        "technical_score": technical_score,
        "options_score": options_score,
        "strategy_alignment": alignment,
        "technical_available": technical_available,
        "options_available": options_available,
        "market_hours": market,
        "blockers": blockers,
        "warnings": warnings,
        "action": action,
        "best_row": best_row,
        "technical": tech,
        "diagnostics": {
            "technical_file": str(_V23_TECH_FILE),
            "decision_file": str(_V23_DECISION_FILE),
            "fallback_unified_file": str(_V23_UNIFIED_FILE),
            "options_rows_found": len(rows),
        },
    }


@app.get("/v23_trade_readiness/{ticker}")
async def v23_trade_readiness(ticker: str):
    return _v23_build_trade_readiness(ticker)


@app.get("/v23_trade_decision/{ticker}")
async def v23_trade_decision(ticker: str):
    return _v23_build_trade_readiness(ticker)


@app.get("/v23_system_status")
async def v23_system_status():
    rows, raw = _v23_get_decision_rows()
    tickers = set()

    if isinstance(rows, list):
        for r in rows:
            if isinstance(r, dict) and r.get("ticker"):
                tickers.add(str(r.get("ticker")).upper())

    tech_data = _v23_read_json(_V23_TECH_FILE, {})
    technical_tickers = []

    if isinstance(tech_data, dict):
        if "snapshots" in tech_data and isinstance(tech_data.get("snapshots"), dict):
            technical_tickers = sorted([str(x).upper() for x in tech_data.get("snapshots", {}).keys()])
        elif tech_data.get("ticker"):
            technical_tickers = [str(tech_data.get("ticker")).upper()]
        else:
            technical_tickers = sorted([str(x).upper() for x in tech_data.keys() if isinstance(x, str)])

    return {
        "engine": "V23_TRADE_READINESS_EXECUTION_GUARD",
        "generated_at": _v23_now(),
        "status": "OK",
        "decision_rows_found": len(rows),
        "decision_tickers": sorted(tickers),
        "technical_snapshot_available": bool(technical_tickers),
        "technical_tickers": technical_tickers,
        "endpoints": {
            "v23_trade_readiness_example": "/v23_trade_readiness/QQQ",
            "v23_trade_decision_example": "/v23_trade_decision/QQQ",
            "v23_dashboard": "/v23_dashboard",
            "v23_dashboard_ticker_example": "/v23_dashboard/QQQ",
        },
    }


def _v23_html_escape(x):
    try:
        import html
        return html.escape(str(x))
    except Exception:
        return str(x)


def _v23_badge(state):
    color = {
        "ENTRY_READY": "#16a34a",
        "WAIT_MARKET_OPEN": "#64748b",
        "WAIT_TECHNICAL_DATA": "#64748b",
        "WAIT_OPTIONS_DATA": "#64748b",
        "RADAR_ONLY": "#f59e0b",
        "BLOCKED": "#dc2626",
        "NO_DATA": "#64748b",
    }.get(str(state), "#64748b")
    return f'<span style="background:{color};color:white;padding:6px 10px;border-radius:999px;font-weight:700;">{_v23_html_escape(state)}</span>'


@app.get("/v23_dashboard/{ticker}", response_class=HTMLResponse)
async def v23_dashboard_ticker(ticker: str):
    d = _v23_build_trade_readiness(ticker)

    blockers = d.get("blockers") or []
    warnings = d.get("warnings") or []
    market = d.get("market_hours") or {}

    html_body = f"""
    <html>
    <head>
        <title>V23 Trade Readiness - {_v23_html_escape(ticker)}</title>
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif;
                background:#f4f6f8;
                color:#0f172a;
                margin:40px;
            }}
            .hero {{
                background:#111827;
                color:white;
                padding:32px;
                border-radius:24px;
                margin-bottom:24px;
            }}
            .grid {{
                display:grid;
                grid-template-columns: repeat(4, 1fr);
                gap:16px;
                margin-bottom:24px;
            }}
            .card {{
                background:white;
                padding:20px;
                border-radius:18px;
                box-shadow:0 10px 25px rgba(15,23,42,0.08);
            }}
            .label {{
                color:#64748b;
                font-size:12px;
                letter-spacing:.08em;
                text-transform:uppercase;
                font-weight:700;
            }}
            .value {{
                font-size:24px;
                font-weight:800;
                margin-top:8px;
            }}
            ul {{
                margin-top:8px;
            }}
            table {{
                width:100%;
                border-collapse:collapse;
                background:white;
                border-radius:18px;
                overflow:hidden;
            }}
            th, td {{
                text-align:left;
                padding:12px 14px;
                border-bottom:1px solid #e5e7eb;
                font-size:14px;
            }}
            th {{
                color:#64748b;
                font-size:12px;
                letter-spacing:.08em;
                text-transform:uppercase;
            }}
        </style>
    </head>
    <body>
        <h1>V23 Trade Readiness — {_v23_html_escape(ticker).upper()}</h1>
        <div class="hero">
            <div class="label">Estado operativo</div>
            <h2>{_v23_badge(d.get("final_state"))}</h2>
            <h1>{_v23_html_escape(d.get("action"))}</h1>
            <p>Generado: {_v23_html_escape(d.get("generated_at"))}</p>
        </div>

        <div class="grid">
            <div class="card"><div class="label">Operable</div><div class="value">{'Sí' if d.get("can_operate") else 'No'}</div></div>
            <div class="card"><div class="label">Estrategia</div><div class="value">{_v23_html_escape(d.get("strategy"))}</div></div>
            <div class="card"><div class="label">Sesgo técnico</div><div class="value">{_v23_html_escape(d.get("technical_bias"))}</div></div>
            <div class="card"><div class="label">Alineación</div><div class="value">{_v23_html_escape(d.get("strategy_alignment"))}</div></div>
        </div>

        <div class="grid">
            <div class="card"><div class="label">Score técnico</div><div class="value">{_v23_html_escape(d.get("technical_score"))}</div></div>
            <div class="card"><div class="label">Score opciones</div><div class="value">{_v23_html_escape(d.get("options_score"))}</div></div>
            <div class="card"><div class="label">Mercado</div><div class="value">{_v23_html_escape(market.get("status"))}</div></div>
            <div class="card"><div class="label">Bid/Ask opciones</div><div class="value">{'Confiable' if market.get("options_bidask_expected") else 'No confiable'}</div></div>
        </div>

        <div class="card">
            <h2>Bloqueadores</h2>
            <ul>{"".join(f"<li>{_v23_html_escape(x)}</li>" for x in blockers) or "<li>Sin bloqueadores críticos.</li>"}</ul>
        </div>

        <br/>

        <div class="card">
            <h2>Advertencias</h2>
            <ul>{"".join(f"<li>{_v23_html_escape(x)}</li>" for x in warnings) or "<li>Sin advertencias relevantes.</li>"}</ul>
        </div>

        <br/>

        <table>
            <tr>
                <th>Campo</th>
                <th>Valor</th>
            </tr>
            <tr><td>Technical available</td><td>{_v23_html_escape(d.get("technical_available"))}</td></tr>
            <tr><td>Options available</td><td>{_v23_html_escape(d.get("options_available"))}</td></tr>
            <tr><td>Market label</td><td>{_v23_html_escape(market.get("label"))}</td></tr>
            <tr><td>Next check</td><td>{_v23_html_escape(market.get("next_check"))}</td></tr>
        </table>

        <p style="margin-top:30px;"><a href="/v23_system_status">Ver V23 system status</a></p>
    </body>
    </html>
    """

    return HTMLResponse(content=html_body)


@app.get("/v23_dashboard", response_class=HTMLResponse)
async def v23_dashboard():
    status = await v23_system_status()
    tickers = status.get("decision_tickers") or status.get("technical_tickers") or ["QQQ"]

    cards = ""
    for t in tickers:
        d = _v23_build_trade_readiness(t)
        cards += f"""
        <tr>
            <td><a href="/v23_dashboard/{_v23_html_escape(t)}">{_v23_html_escape(t)}</a></td>
            <td>{_v23_badge(d.get("final_state"))}</td>
            <td>{_v23_html_escape(d.get("strategy"))}</td>
            <td>{_v23_html_escape(d.get("technical_bias"))}</td>
            <td>{'Sí' if d.get("can_operate") else 'No'}</td>
            <td>{_v23_html_escape(d.get("action"))}</td>
        </tr>
        """

    html_body = f"""
    <html>
    <head>
        <title>V23 Dashboard</title>
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif;
                background:#f4f6f8;
                color:#0f172a;
                margin:40px;
            }}
            .hero {{
                background:#111827;
                color:white;
                padding:32px;
                border-radius:24px;
                margin-bottom:24px;
            }}
            table {{
                width:100%;
                border-collapse:collapse;
                background:white;
                border-radius:18px;
                overflow:hidden;
                box-shadow:0 10px 25px rgba(15,23,42,0.08);
            }}
            th, td {{
                text-align:left;
                padding:14px;
                border-bottom:1px solid #e5e7eb;
                font-size:14px;
            }}
            th {{
                color:#64748b;
                font-size:12px;
                letter-spacing:.08em;
                text-transform:uppercase;
            }}
        </style>
    </head>
    <body>
        <h1>V23 — Trade Readiness Dashboard</h1>
        <div class="hero">
            <h2>Execution Guard activo</h2>
            <p>Este dashboard consolida técnico + opciones + estado de mercado para evitar operar sin confirmaciones críticas.</p>
            <p>Generado: {_v23_html_escape(_v23_now())}</p>
        </div>
        <table>
            <tr>
                <th>Ticker</th>
                <th>Estado</th>
                <th>Estrategia</th>
                <th>Sesgo técnico</th>
                <th>Operable</th>
                <th>Acción</th>
            </tr>
            {cards}
        </table>
    </body>
    </html>
    """

    return HTMLResponse(content=html_body)

# ============================================================
# END V23 TRADE READINESS & EXECUTION GUARD
# ============================================================
'''

if "V23 TRADE READINESS & EXECUTION GUARD" not in s:
    s = s.rstrip() + "\n\n" + block + "\n"
else:
    print("V23 block already exists. No duplicate inserted.")

p.write_text(s)
print("V23 trade readiness patch applied.")
