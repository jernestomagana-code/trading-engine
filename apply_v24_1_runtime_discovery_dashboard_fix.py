from pathlib import Path
import re

p = Path("app/main.py")
s = p.read_text()

Path("app/main_backup_before_v24_1_runtime_discovery_dashboard_fix.py").write_text(s)

marker = "# === V24.1 RUNTIME DISCOVERY + SAFE DASHBOARD FIX ==="

block = r'''

# === V24.1 RUNTIME DISCOVERY + SAFE DASHBOARD FIX ===
from pathlib import Path as _V241Path
from datetime import datetime as _V241DateTime, timezone as _V241Timezone
import json as _v241_json

_V241_RUNTIME = _V241Path("runtime")
_V241_RUNTIME.mkdir(exist_ok=True)

def _v241_now():
    return _V241DateTime.now(_V241Timezone.utc).isoformat()

def _v241_read_json(path):
    try:
        path = _V241Path(path)
        if not path.exists():
            return None
        txt = path.read_text().strip()
        if not txt:
            return None
        return _v241_json.loads(txt)
    except Exception as e:
        return {"__read_error__": str(e), "__path__": str(path)}

def _v241_runtime_json_files():
    files = []
    try:
        for f in _V241_RUNTIME.glob("*.json"):
            files.append(str(f))
    except Exception:
        pass

    root_candidates = [
        "decision_snapshot.json",
        "decision_desk_snapshot.json",
        "technical_snapshot_by_ticker.json",
        "technical_snapshot_by_ticker_safe.json",
        "v18_decision_snapshot.json",
        "v18_decision_desk_snapshot.json",
    ]

    for name in root_candidates:
        if _V241Path(name).exists():
            files.append(name)

    return sorted(list(set(files)))

def _v241_extract_rows_from_any(obj):
    rows = []

    if obj is None:
        return rows

    if isinstance(obj, list):
        return [x for x in obj if isinstance(x, dict)]

    if not isinstance(obj, dict):
        return rows

    # Si el objeto mismo parece una fila operativa
    if any(k in obj for k in ["ticker", "strategy", "decision", "final_state", "can_operate", "score", "price"]):
        rows.append(obj)

    keys = [
        "rows", "top", "top_3", "top_5", "items", "data", "records",
        "opportunities", "decision_rows", "sample_rows"
    ]

    for k in keys:
        v = obj.get(k)
        if isinstance(v, list):
            rows.extend([x for x in v if isinstance(x, dict)])
        elif isinstance(v, dict):
            rows.extend(_v241_extract_rows_from_any(v))

    for k in ["best", "best_row", "best_opportunity", "next_best_action", "best_fusion_opportunity"]:
        v = obj.get(k)
        if isinstance(v, dict):
            rows.append(v)

    for k in ["summary", "by_ticker", "by_strategy", "fusion_counts", "options"]:
        v = obj.get(k)
        if isinstance(v, dict):
            rows.extend(_v241_extract_rows_from_any(v))
        elif isinstance(v, list):
            rows.extend([x for x in v if isinstance(x, dict)])

    # Búsqueda profunda limitada en diccionarios anidados
    for v in obj.values():
        if isinstance(v, dict):
            rows.extend(_v241_extract_rows_from_any(v))
        elif isinstance(v, list):
            for item in v:
                if isinstance(item, dict):
                    rows.extend(_v241_extract_rows_from_any(item))

    # Deduplicar conservando orden
    seen = set()
    clean = []
    for r in rows:
        key = str(sorted(r.items()))[:500]
        if key not in seen:
            seen.add(key)
            clean.append(r)

    return clean

def _v241_ticker(row):
    if not isinstance(row, dict):
        return ""
    return str(
        row.get("ticker")
        or row.get("symbol")
        or row.get("underlying")
        or row.get("underlying_symbol")
        or row.get("option_symbol")
        or ""
    ).upper().strip()

def _v241_strategy(row):
    if not isinstance(row, dict):
        return "UNKNOWN"
    return str(
        row.get("strategy")
        or row.get("strategy_hint")
        or row.get("best_strategy")
        or row.get("primary_focus")
        or row.get("setup")
        or "UNKNOWN"
    ).upper().strip()

def _v241_score(row):
    if not isinstance(row, dict):
        return None
    for k in ["combined_score", "score", "master_score", "technical_score", "options_score", "entry_score"]:
        try:
            v = row.get(k)
            if v is not None:
                return float(v)
        except Exception:
            pass
    return None

def _v241_can_operate(row):
    if not isinstance(row, dict):
        return False

    if row.get("can_operate") is True or row.get("can_trade") is True:
        return True

    decision = str(row.get("decision") or row.get("final_decision") or row.get("final_state") or "").upper()
    state = str(row.get("state") or row.get("fusion_state") or "").upper()

    if "ENTRY" in decision or "ENTRY" in state:
        return True

    return False

def _v241_load_all_runtime_context():
    files = _v241_runtime_json_files()
    all_rows = []
    file_report = []

    technical_by_ticker = {}

    for f in files:
        obj = _v241_read_json(f)

        report = {
            "file": f,
            "loaded": obj is not None,
            "type": type(obj).__name__,
            "rows_found": 0,
            "tickers": [],
            "technical_like": False,
            "error": None,
        }

        if isinstance(obj, dict) and obj.get("__read_error__"):
            report["error"] = obj.get("__read_error__")
            file_report.append(report)
            continue

        rows = _v241_extract_rows_from_any(obj)
        report["rows_found"] = len(rows)

        for r in rows:
            t = _v241_ticker(r)
            if t:
                report["tickers"].append(t)
            all_rows.append(r)

        # technical snapshot style: {"QQQ": {...}}
        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(v, dict) and any(x in v for x in ["trend", "bias", "score", "rsi", "adx", "vwap_position"]):
                    technical_by_ticker[str(k).upper()] = v
                    report["technical_like"] = True

            # technical single object style
            t = _v241_ticker(obj)
            if t and any(x in obj for x in ["trend", "bias", "score", "rsi", "adx", "vwap_position"]):
                technical_by_ticker[t] = obj
                report["technical_like"] = True

        report["tickers"] = sorted(list(set(report["tickers"])))
        file_report.append(report)

    tickers = sorted(list(set([_v241_ticker(r) for r in all_rows if _v241_ticker(r)] + list(technical_by_ticker.keys()))))

    return {
        "files": files,
        "file_report": file_report,
        "rows": all_rows,
        "rows_found": len(all_rows),
        "technical_by_ticker": technical_by_ticker,
        "technical_tickers": sorted(list(technical_by_ticker.keys())),
        "tickers": tickers,
    }

def _v241_market_hours():
    try:
        fn = globals().get("market_hours")
        if callable(fn):
            return fn()
    except Exception:
        pass
    return {
        "status": "UNKNOWN",
        "label": "Market hours unknown",
        "is_regular_market_open": None,
        "options_bidask_expected": None,
    }

def _v241_pick_best(ticker=None):
    ctx = _v241_load_all_runtime_context()
    ticker = str(ticker or "").upper().strip()

    rows = []
    for r in ctx["rows"]:
        if ticker and _v241_ticker(r) != ticker:
            continue
        rows.append(r)

    def rank(r):
        entry = 10000 if _v241_can_operate(r) else 0
        score = _v241_score(r) or 0
        has_price = 50 if r.get("price") or r.get("premium") or r.get("mark_price") else 0
        return entry + score + has_price

    best = sorted(rows, key=rank, reverse=True)[0] if rows else None
    return ctx, best

def _v241_trade_decision(ticker):
    ticker = str(ticker or "").upper().strip()
    ctx, best = _v241_pick_best(ticker)
    tech = ctx["technical_by_ticker"].get(ticker)
    mh = _v241_market_hours()

    has_rows = best is not None
    has_tech = tech is not None

    market_status = str((mh or {}).get("status") or "").upper()
    options_bidask_expected = bool((mh or {}).get("options_bidask_expected"))

    if not has_rows and not has_tech:
        final_state = "NO_DATA"
        can_operate = False
        blocker = "NO_RUNTIME_ROWS_OR_TECHNICAL"
        action = f"{ticker}: no hay datos detectados en runtime para opciones ni técnico."
        severity = "red"
    elif not has_tech:
        final_state = "WAIT_TECHNICAL_DATA"
        can_operate = False
        blocker = "NO_TECHNICAL_SNAPSHOT"
        action = f"{ticker}: hay datos de opciones/decisión, pero falta snapshot técnico."
        severity = "gray"
    elif not has_rows:
        final_state = "WAIT_OPTIONS_DATA"
        can_operate = False
        blocker = "NO_OPTIONS_OR_DECISION_ROWS"
        action = f"{ticker}: hay técnico disponible, pero faltan oportunidades/opciones."
        severity = "gray"
    elif market_status not in ["REGULAR_OPTIONS_SESSION", "REGULAR_MARKET_OPEN"] and not options_bidask_expected:
        final_state = "WAIT_MARKET_OPEN"
        can_operate = False
        blocker = "OPTIONS_MARKET_NOT_RELIABLE"
        action = "No operar ahora. Esperar ventana confiable de mercado/opciones."
        severity = "gray"
    elif _v241_can_operate(best):
        final_state = "ENTRY_READY"
        can_operate = True
        blocker = None
        action = "Entrada potencial lista. Validar riesgo, tamaño, spread, liquidez y confirmación final."
        severity = "green"
    else:
        final_state = "RADAR"
        can_operate = False
        blocker = "NOT_FULLY_CONFIRMED"
        action = "Mantener en radar. Aún no cumple confirmaciones completas."
        severity = "yellow"

    return {
        "engine": "V24_1_RUNTIME_DISCOVERY_SAFE_DASHBOARD",
        "generated_at": _v241_now(),
        "ticker": ticker,
        "status": "OK",
        "final_state": final_state,
        "decision": final_state,
        "can_operate": can_operate,
        "severity": severity,
        "main_blocker": blocker,
        "action": action,
        "strategy": _v241_strategy(best) if best else "UNKNOWN",
        "score": _v241_score(best) if best else None,
        "technical": {
            "available": has_tech,
            "snapshot": tech,
            "bias": str((tech or {}).get("bias") or (tech or {}).get("trend") or "UNKNOWN").upper(),
            "score": (tech or {}).get("score"),
        },
        "options": {
            "available": has_rows,
            "rows_found_total": ctx["rows_found"],
            "best_row": best,
        },
        "market_hours": mh,
        "diagnostics": {
            "runtime_files": ctx["files"],
            "technical_tickers": ctx["technical_tickers"],
            "tickers_detected": ctx["tickers"],
        }
    }

@app.get("/v24_1_runtime_inventory")
async def v24_1_runtime_inventory():
    ctx = _v241_load_all_runtime_context()
    return {
        "engine": "V24_1_RUNTIME_DISCOVERY_SAFE_DASHBOARD",
        "generated_at": _v241_now(),
        "status": "OK",
        "runtime_files": ctx["files"],
        "file_report": ctx["file_report"],
        "rows_found_total": ctx["rows_found"],
        "technical_tickers": ctx["technical_tickers"],
        "tickers_detected": ctx["tickers"],
    }

@app.get("/v24_1_trade_decision/{ticker}")
async def v24_1_trade_decision(ticker: str):
    return _v241_trade_decision(ticker)

def _v241_escape(x):
    import html
    return html.escape(str(x if x is not None else ""))

def _v241_badge(state):
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

def _v241_dashboard_html(ticker=None):
    try:
        ctx = _v241_load_all_runtime_context()
        tickers = ctx["tickers"]

        if ticker:
            tickers = [str(ticker).upper().strip()]

        if not tickers:
            tickers = ["QQQ"]

        rows_html = ""
        decisions = []

        for t in tickers:
            d = _v241_trade_decision(t)
            decisions.append(d)
            color = _v241_badge(d.get("final_state"))
            rows_html += f"""
            <tr>
                <td><a href="/v24_1_dashboard/{_v241_escape(t)}">{_v241_escape(t)}</a></td>
                <td><span class="badge" style="background:{color}">{_v241_escape(d.get("final_state"))}</span></td>
                <td>{_v241_escape(d.get("strategy"))}</td>
                <td>{_v241_escape(d.get("technical", {}).get("bias"))}</td>
                <td>{_v241_escape(d.get("score"))}</td>
                <td>{'Sí' if d.get("can_operate") else 'No'}</td>
                <td>{_v241_escape(d.get("main_blocker"))}</td>
                <td>{_v241_escape(d.get("action"))}</td>
            </tr>
            """

        headline = "Execution Guard activo"
        if any(d.get("can_operate") for d in decisions):
            headline = "Entrada potencial detectada"
        elif any(d.get("final_state") == "RADAR" for d in decisions):
            headline = "Oportunidades en radar"

        return f"""
        <!doctype html>
        <html>
        <head>
            <meta charset="utf-8"/>
            <meta name="viewport" content="width=device-width, initial-scale=1"/>
            <title>V24.1 Runtime Discovery Dashboard</title>
            <style>
                body {{
                    font-family: Inter, Arial, sans-serif;
                    background:#f6f7fb;
                    color:#0f172a;
                    padding:32px;
                }}
                h1 {{ font-size:34px; margin-bottom:20px; }}
                .hero {{
                    background:#0f172a;
                    color:white;
                    border-radius:24px;
                    padding:34px;
                    margin-bottom:24px;
                }}
                .hero h2 {{ margin:0 0 12px 0; font-size:26px; }}
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
                    box-shadow:0 12px 28px rgba(15,23,42,.08);
                }}
                .num {{ font-size:30px; font-weight:800; }}
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
                    padding:13px 15px;
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
                    color:white;
                    padding:6px 10px;
                    border-radius:999px;
                    font-weight:800;
                    font-size:12px;
                    display:inline-block;
                }}
                .footer {{
                    margin-top:24px;
                    font-size:13px;
                    color:#64748b;
                }}
            </style>
        </head>
        <body>
            <h1>V24.1 — Runtime Discovery Dashboard</h1>
            <div class="hero">
                <h2>{_v241_escape(headline)}</h2>
                <p>Busca automáticamente archivos runtime JSON y consolida técnico + opciones + decisión + market hours.</p>
                <p>Generado: {_v241_escape(_v241_now())}</p>
            </div>

            <div class="grid">
                <div class="card"><div>Runtime files</div><div class="num">{len(ctx["files"])}</div></div>
                <div class="card"><div>Rows encontradas</div><div class="num">{ctx["rows_found"]}</div></div>
                <div class="card"><div>Technical tickers</div><div class="num">{len(ctx["technical_tickers"])}</div></div>
                <div class="card"><div>Tickers detectados</div><div class="num">{len(tickers)}</div></div>
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
                        <th>Bloqueador</th>
                        <th>Acción</th>
                    </tr>
                </thead>
                <tbody>{rows_html}</tbody>
            </table>

            <div class="footer">
                Endpoints: /v24_1_runtime_inventory · /v24_1_trade_decision/QQQ · /v24_1_dashboard · /v24_1_dashboard/QQQ
            </div>
        </body>
        </html>
        """
    except Exception as e:
        return f"""
        <html><body style="font-family:Arial;padding:30px">
        <h1>V24.1 Dashboard Error Capturado</h1>
        <p>El dashboard no explotó el servicio, pero capturó este error:</p>
        <pre>{_v241_escape(type(e).__name__)}: {_v241_escape(e)}</pre>
        <p>Revisar /v24_1_runtime_inventory para diagnóstico.</p>
        </body></html>
        """

@app.get("/v24_1_dashboard")
async def v24_1_dashboard():
    from fastapi.responses import HTMLResponse
    return HTMLResponse(_v241_dashboard_html())

@app.get("/v24_1_dashboard/{ticker}")
async def v24_1_dashboard_ticker(ticker: str):
    from fastapi.responses import HTMLResponse
    return HTMLResponse(_v241_dashboard_html(ticker))

# === END V24.1 RUNTIME DISCOVERY + SAFE DASHBOARD FIX ===
'''

if marker not in s:
    s = s.rstrip() + "\n\n" + block + "\n"
else:
    print("V24.1 already exists. No duplicate inserted.")

p.write_text(s)
print("V24.1 Runtime Discovery + Safe Dashboard patch applied.")
