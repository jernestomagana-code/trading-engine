from pathlib import Path

main = Path("app/main.py")
m = main.read_text()

v19_block = r'''
# ============================================================
# SUPER ENGINE BOLSA — V19 OPERATIONAL TRADING DASHBOARD
# ============================================================

from fastapi.responses import HTMLResponse as _v19_HTMLResponse
from datetime import datetime as _v19_datetime, timezone as _v19_timezone
import html as _v19_html

def _v19_safe_data():
    try:
        return _v18_api_load_snapshot()
    except Exception as e:
        return {
            "engine": "V19_OPERATIONAL_TRADING_DASHBOARD",
            "status": "ERROR",
            "generated_at": _v19_datetime.now(_v19_timezone.utc).isoformat(),
            "summary": {
                "entry": 0,
                "manage_position": 0,
                "radar": 0,
                "wait_greeks": 0,
                "wait_data": 0,
                "blocked": 0,
                "total": 0,
            },
            "next_best_action": None,
            "recommendation": f"No se pudo cargar snapshot: {e}",
            "by_ticker": [],
            "by_strategy": [],
            "top": [],
            "health": {
                "snapshot_available": False,
                "rows_captured": 0,
                "can_operate_count": 0,
                "remote_ingested": False,
            },
        }

def _v19_parse_dt(value):
    try:
        if not value:
            return None
        v = str(value).replace("Z", "+00:00")
        return _v19_datetime.fromisoformat(v)
    except Exception:
        return None

def _v19_snapshot_age_minutes(data):
    dt = _v19_parse_dt(data.get("remote_ingested_at") or data.get("generated_at"))
    if not dt:
        return None
    try:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_v19_timezone.utc)
        now = _v19_datetime.now(_v19_timezone.utc)
        return round((now - dt).total_seconds() / 60, 2)
    except Exception:
        return None

def _v19_freshness(data):
    age = _v19_snapshot_age_minutes(data)
    if age is None:
        return {
            "status": "UNKNOWN",
            "label": "Sin timestamp",
            "age_minutes": None,
            "color": "#64748b",
        }
    if age <= 5:
        return {
            "status": "FRESH",
            "label": f"Fresh: {age} min",
            "age_minutes": age,
            "color": "#16a34a",
        }
    if age <= 15:
        return {
            "status": "WARNING",
            "label": f"Warning: {age} min",
            "age_minutes": age,
            "color": "#f59e0b",
        }
    return {
        "status": "STALE",
        "label": f"Stale: {age} min",
        "age_minutes": age,
        "color": "#dc2626",
    }

def _v19_decision_color(decision):
    d = str(decision or "").upper()
    if d == "ENTRY":
        return "#16a34a"
    if d == "MANAGE_POSITION":
        return "#2563eb"
    if d == "RADAR":
        return "#f59e0b"
    if d == "WAIT_GREEKS":
        return "#fb923c"
    if d == "WAIT_DATA":
        return "#64748b"
    if d == "BLOCKED":
        return "#dc2626"
    return "#64748b"

def _v19_decision_label(decision):
    d = str(decision or "").upper()
    labels = {
        "ENTRY": "OPERAR / VALIDAR",
        "MANAGE_POSITION": "GESTIONAR POSICIÓN",
        "RADAR": "RADAR",
        "WAIT_GREEKS": "ESPERAR GRIEGAS",
        "WAIT_DATA": "ESPERAR DATOS",
        "BLOCKED": "BLOQUEADO",
    }
    return labels.get(d, d or "SIN DECISIÓN")

def _v19_market_call(data):
    summary = data.get("summary", {}) or {}
    nba = data.get("next_best_action")

    entry = int(summary.get("entry") or 0)
    manage = int(summary.get("manage_position") or 0)
    radar = int(summary.get("radar") or 0)
    blocked = int(summary.get("blocked") or 0)
    wait_greeks = int(summary.get("wait_greeks") or 0)
    wait_data = int(summary.get("wait_data") or 0)

    if manage > 0:
        return {
            "market_call": "GESTIONAR POSICIONES",
            "can_operate_now": False,
            "tone": "blue",
            "message": "Hay posiciones que requieren revisión antes de abrir nuevas operaciones.",
        }

    if entry > 0:
        can_operate = bool(nba and nba.get("can_operate"))
        return {
            "market_call": "POSIBLE ENTRADA",
            "can_operate_now": can_operate,
            "tone": "green" if can_operate else "yellow",
            "message": "Existe al menos una oportunidad en ENTRY. Validar riesgo y liquidez antes de ejecutar.",
        }

    if radar > 0:
        return {
            "market_call": "RADAR",
            "can_operate_now": False,
            "tone": "yellow",
            "message": "Hay oportunidades interesantes, pero todavía no son entrada operable.",
        }

    if wait_greeks > 0 or wait_data > 0:
        return {
            "market_call": "ESPERAR",
            "can_operate_now": False,
            "tone": "gray",
            "message": "El sistema requiere más datos, griegas o confirmaciones antes de operar.",
        }

    if blocked > 0:
        return {
            "market_call": "BLOQUEADO",
            "can_operate_now": False,
            "tone": "red",
            "message": "Las oportunidades actuales están bloqueadas por reglas de seguridad o calidad.",
        }

    return {
        "market_call": "SIN OPORTUNIDAD",
        "can_operate_now": False,
        "tone": "gray",
        "message": "No hay oportunidades relevantes capturadas en el último ciclo.",
    }

def _v19_escape(value):
    return _v19_html.escape(str(value if value is not None else ""))

def _v19_money(value):
    try:
        if value is None:
            return "—"
        return f"{float(value):.2f}"
    except Exception:
        return _v19_escape(value) if value not in [None, ""] else "—"

def _v19_card(title, value, subtitle="", color="#0f172a"):
    return f"""
    <div class="card">
      <div class="card-title">{_v19_escape(title)}</div>
      <div class="card-value" style="color:{color};">{_v19_escape(value)}</div>
      <div class="card-subtitle">{_v19_escape(subtitle)}</div>
    </div>
    """

def _v19_top_rows_html(rows, limit=25):
    if not rows:
        return """
        <tr>
          <td colspan="9" class="empty">Sin oportunidades capturadas.</td>
        </tr>
        """

    html_rows = []
    for row in rows[:limit]:
        decision = row.get("decision")
        color = _v19_decision_color(decision)
        missing = row.get("missing_confirmations") or []
        if isinstance(missing, list):
            missing_text = ", ".join(str(x) for x in missing) if missing else "—"
        else:
            missing_text = str(missing) if missing else "—"

        can_operate = "Sí" if row.get("can_operate") else "No"
        action = row.get("recommendation") or "—"

        html_rows.append(f"""
        <tr>
          <td class="ticker">{_v19_escape(row.get("ticker"))}</td>
          <td>{_v19_escape(row.get("strategy"))}</td>
          <td><span class="pill" style="background:{color};">{_v19_escape(_v19_decision_label(decision))}</span></td>
          <td class="num">{_v19_escape(row.get("score"))}</td>
          <td class="num">{_v19_money(row.get("price"))}</td>
          <td>{_v19_escape(row.get("data_quality"))}</td>
          <td>{_v19_escape(missing_text)}</td>
          <td>{_v19_escape(can_operate)}</td>
          <td class="small">{_v19_escape(action)}</td>
        </tr>
        """)

    return "\n".join(html_rows)

def _v19_group_rows_html(items, group_name):
    if not items:
        return """
        <tr>
          <td colspan="8" class="empty">Sin datos.</td>
        </tr>
        """

    rows = []
    for item in items:
        best = item.get("best") or {}
        rows.append(f"""
        <tr>
          <td class="ticker">{_v19_escape(item.get(group_name))}</td>
          <td class="num">{_v19_escape(item.get("total", 0))}</td>
          <td class="num green">{_v19_escape(item.get("entry", 0))}</td>
          <td class="num amber">{_v19_escape(item.get("radar", 0))}</td>
          <td class="num orange">{_v19_escape(item.get("wait_greeks", 0))}</td>
          <td class="num gray">{_v19_escape(item.get("wait_data", 0))}</td>
          <td class="num red">{_v19_escape(item.get("blocked", 0))}</td>
          <td class="small">{_v19_escape(best.get("strategy") or best.get("ticker") or "—")} / {_v19_escape(best.get("decision") or "—")}</td>
        </tr>
        """)
    return "\n".join(rows)

def _v19_css():
    return """
    <style>
      body {
        margin: 0;
        padding: 0;
        background: #f8fafc;
        color: #0f172a;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
      }
      .page {
        max-width: 1380px;
        margin: 0 auto;
        padding: 28px;
      }
      .header {
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: 18px;
        margin-bottom: 22px;
      }
      h1 {
        margin: 0;
        font-size: 30px;
        letter-spacing: -0.03em;
      }
      .muted {
        color: #64748b;
        font-size: 13px;
      }
      .status {
        padding: 10px 14px;
        border-radius: 14px;
        color: white;
        font-weight: 700;
        white-space: nowrap;
      }
      .hero {
        background: linear-gradient(135deg, #0f172a, #1e293b);
        color: white;
        border-radius: 24px;
        padding: 24px;
        margin-bottom: 22px;
        box-shadow: 0 20px 50px rgba(15, 23, 42, 0.18);
      }
      .hero-grid {
        display: grid;
        grid-template-columns: 1.2fr 1fr;
        gap: 22px;
      }
      .hero-label {
        color: #cbd5e1;
        font-size: 12px;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        margin-bottom: 8px;
      }
      .hero-title {
        font-size: 38px;
        font-weight: 800;
        letter-spacing: -0.04em;
        margin-bottom: 8px;
      }
      .hero-message {
        color: #e2e8f0;
        font-size: 16px;
        line-height: 1.45;
      }
      .next-box {
        background: rgba(255,255,255,0.08);
        border: 1px solid rgba(255,255,255,0.12);
        border-radius: 18px;
        padding: 18px;
      }
      .next-title {
        font-size: 22px;
        font-weight: 800;
        margin-bottom: 6px;
      }
      .next-subtitle {
        color: #cbd5e1;
        font-size: 14px;
        line-height: 1.4;
      }
      .grid {
        display: grid;
        grid-template-columns: repeat(6, 1fr);
        gap: 14px;
        margin-bottom: 22px;
      }
      .card {
        background: white;
        border-radius: 18px;
        padding: 18px;
        box-shadow: 0 10px 28px rgba(15, 23, 42, 0.08);
        border: 1px solid #e2e8f0;
      }
      .card-title {
        color: #64748b;
        font-size: 12px;
        text-transform: uppercase;
        letter-spacing: 0.07em;
        font-weight: 700;
      }
      .card-value {
        font-size: 28px;
        font-weight: 850;
        margin-top: 8px;
      }
      .card-subtitle {
        color: #64748b;
        font-size: 12px;
        margin-top: 5px;
      }
      .section {
        background: white;
        border-radius: 22px;
        padding: 20px;
        margin-bottom: 22px;
        border: 1px solid #e2e8f0;
        box-shadow: 0 10px 28px rgba(15, 23, 42, 0.06);
      }
      .section h2 {
        margin: 0 0 14px 0;
        font-size: 20px;
      }
      table {
        width: 100%;
        border-collapse: collapse;
        font-size: 13px;
      }
      th {
        text-align: left;
        color: #475569;
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: 0.07em;
        border-bottom: 1px solid #e2e8f0;
        padding: 10px 8px;
      }
      td {
        border-bottom: 1px solid #f1f5f9;
        padding: 10px 8px;
        vertical-align: top;
      }
      tr:hover td {
        background: #f8fafc;
      }
      .ticker {
        font-weight: 800;
      }
      .num {
        text-align: right;
        font-variant-numeric: tabular-nums;
      }
      .small {
        font-size: 12px;
        color: #334155;
        line-height: 1.35;
      }
      .pill {
        color: white;
        border-radius: 999px;
        padding: 5px 9px;
        font-size: 11px;
        font-weight: 800;
        white-space: nowrap;
      }
      .green { color: #16a34a; font-weight: 800; }
      .amber { color: #d97706; font-weight: 800; }
      .orange { color: #ea580c; font-weight: 800; }
      .red { color: #dc2626; font-weight: 800; }
      .gray { color: #64748b; font-weight: 800; }
      .empty {
        text-align: center;
        color: #64748b;
        padding: 30px;
      }
      .two-col {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 22px;
      }
      .footer {
        color: #64748b;
        font-size: 12px;
        text-align: center;
        padding: 18px 0 4px;
      }
      @media (max-width: 1000px) {
        .grid { grid-template-columns: repeat(2, 1fr); }
        .hero-grid { grid-template-columns: 1fr; }
        .two-col { grid-template-columns: 1fr; }
        .header { flex-direction: column; }
      }
    </style>
    """

@app.get("/dashboard_decision", response_class=_v19_HTMLResponse)
def dashboard_decision():
    data = _v19_safe_data()
    summary = data.get("summary", {}) or {}
    health = data.get("health", {}) or {}
    nba = data.get("next_best_action") or {}
    freshness = _v19_freshness(data)
    call = _v19_market_call(data)

    call_color = {
        "green": "#16a34a",
        "yellow": "#f59e0b",
        "gray": "#64748b",
        "red": "#dc2626",
        "blue": "#2563eb",
    }.get(call.get("tone"), "#64748b")

    if nba:
        next_title = f"{nba.get('ticker', '—')} / {nba.get('strategy', '—')}"
        next_subtitle = nba.get("recommendation") or nba.get("reason") or "Sin recomendación."
        next_decision = _v19_decision_label(nba.get("decision"))
    else:
        next_title = "Sin oportunidad"
        next_subtitle = data.get("recommendation") or "No hay oportunidad capturada."
        next_decision = "SIN DECISIÓN"

    html = f"""
    <!doctype html>
    <html>
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>Super Engine Bolsa — Decision Dashboard</title>
      {_v19_css()}
    </head>
    <body>
      <div class="page">
        <div class="header">
          <div>
            <h1>Super Engine Bolsa — Operational Trading Dashboard</h1>
            <div class="muted">
              Engine: {_v19_escape(data.get("engine"))} · Generated: {_v19_escape(data.get("generated_at"))} · Remote ingested: {_v19_escape(data.get("remote_ingested_at", "—"))}
            </div>
          </div>
          <div class="status" style="background:{freshness.get('color')};">
            {_v19_escape(freshness.get("label"))}
          </div>
        </div>

        <div class="hero">
          <div class="hero-grid">
            <div>
              <div class="hero-label">Estado operativo</div>
              <div class="hero-title" style="color:{call_color};">{_v19_escape(call.get("market_call"))}</div>
              <div class="hero-message">{_v19_escape(call.get("message"))}</div>
            </div>
            <div class="next-box">
              <div class="hero-label">Next Best Action</div>
              <div class="next-title">{_v19_escape(next_title)}</div>
              <div class="pill" style="display:inline-block;background:{_v19_decision_color(nba.get("decision"))};margin-bottom:10px;">{_v19_escape(next_decision)}</div>
              <div class="next-subtitle">{_v19_escape(next_subtitle)}</div>
            </div>
          </div>
        </div>

        <div class="grid">
          {_v19_card("Entry", summary.get("entry", 0), "Entradas posibles", "#16a34a")}
          {_v19_card("Manage", summary.get("manage_position", 0), "Gestión de posición", "#2563eb")}
          {_v19_card("Radar", summary.get("radar", 0), "Oportunidades en observación", "#d97706")}
          {_v19_card("Wait Greeks", summary.get("wait_greeks", 0), "Faltan griegas", "#ea580c")}
          {_v19_card("Wait Data", summary.get("wait_data", 0), "Faltan datos", "#64748b")}
          {_v19_card("Total", summary.get("total", 0), f"Rows: {health.get('rows_captured', 0)}", "#0f172a")}
        </div>

        <div class="section">
          <h2>Oportunidades priorizadas</h2>
          <table>
            <thead>
              <tr>
                <th>Ticker</th>
                <th>Estrategia</th>
                <th>Decisión</th>
                <th class="num">Score</th>
                <th class="num">Prima/Precio</th>
                <th>Calidad</th>
                <th>Falta</th>
                <th>Operable</th>
                <th>Acción</th>
              </tr>
            </thead>
            <tbody>
              {_v19_top_rows_html(data.get("top", []), limit=30)}
            </tbody>
          </table>
        </div>

        <div class="two-col">
          <div class="section">
            <h2>Resumen por ticker</h2>
            <table>
              <thead>
                <tr>
                  <th>Ticker</th>
                  <th class="num">Total</th>
                  <th class="num">Entry</th>
                  <th class="num">Radar</th>
                  <th class="num">Greeks</th>
                  <th class="num">Data</th>
                  <th class="num">Blocked</th>
                  <th>Best</th>
                </tr>
              </thead>
              <tbody>
                {_v19_group_rows_html(data.get("by_ticker", []), "ticker")}
              </tbody>
            </table>
          </div>

          <div class="section">
            <h2>Resumen por estrategia</h2>
            <table>
              <thead>
                <tr>
                  <th>Estrategia</th>
                  <th class="num">Total</th>
                  <th class="num">Entry</th>
                  <th class="num">Radar</th>
                  <th class="num">Greeks</th>
                  <th class="num">Data</th>
                  <th class="num">Blocked</th>
                  <th>Best</th>
                </tr>
              </thead>
              <tbody>
                {_v19_group_rows_html(data.get("by_strategy", []), "strategy")}
              </tbody>
            </table>
          </div>
        </div>

        <div class="section">
          <h2>Conclusión ejecutiva</h2>
          <p class="small" style="font-size:15px;">
            {_v19_escape(data.get("recommendation") or call.get("message"))}
          </p>
          <p class="muted">
            Snapshot available: {_v19_escape(health.get("snapshot_available"))} · Remote ingested: {_v19_escape(health.get("remote_ingested"))} · Can operate count: {_v19_escape(health.get("can_operate_count"))}
          </p>
        </div>

        <div class="footer">
          Super Engine Bolsa · V19 Operational Trading Dashboard
        </div>
      </div>
    </body>
    </html>
    """
    return html

@app.get("/dashboard_ticker/{ticker}", response_class=_v19_HTMLResponse)
def dashboard_ticker(ticker: str):
    data = _v19_safe_data()
    t = str(ticker or "").upper().strip()

    top = [
        row for row in data.get("top", [])
        if str(row.get("ticker", "")).upper() == t
    ]

    ticker_summary = None
    for item in data.get("by_ticker", []):
        if str(item.get("ticker", "")).upper() == t:
            ticker_summary = item
            break

    best = top[0] if top else None
    freshness = _v19_freshness(data)

    if best:
        title = f"{t} — {best.get('strategy')} / {_v19_decision_label(best.get('decision'))}"
        recommendation = best.get("recommendation") or "Sin recomendación."
        reason = best.get("reason") or "Sin razón disponible."
    else:
        title = f"{t} — Sin oportunidad capturada"
        recommendation = f"No hay oportunidades capturadas para {t} en el último ciclo."
        reason = "El ticker no aparece dentro del top operativo actual."

    html = f"""
    <!doctype html>
    <html>
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>{_v19_escape(t)} — Super Engine Bolsa</title>
      {_v19_css()}
    </head>
    <body>
      <div class="page">
        <div class="header">
          <div>
            <h1>{_v19_escape(title)}</h1>
            <div class="muted">Generated: {_v19_escape(data.get("generated_at"))}</div>
          </div>
          <div class="status" style="background:{freshness.get('color')};">
            {_v19_escape(freshness.get("label"))}
          </div>
        </div>

        <div class="hero">
          <div class="hero-grid">
            <div>
              <div class="hero-label">Recomendación</div>
              <div class="hero-title" style="font-size:28px;">{_v19_escape(recommendation)}</div>
              <div class="hero-message">{_v19_escape(reason)}</div>
            </div>
            <div class="next-box">
              <div class="hero-label">Resumen del ticker</div>
              <div class="next-subtitle">
                Total: {_v19_escape((ticker_summary or {}).get("total", 0))}<br>
                Entry: {_v19_escape((ticker_summary or {}).get("entry", 0))}<br>
                Radar: {_v19_escape((ticker_summary or {}).get("radar", 0))}<br>
                Wait Greeks: {_v19_escape((ticker_summary or {}).get("wait_greeks", 0))}<br>
                Blocked: {_v19_escape((ticker_summary or {}).get("blocked", 0))}
              </div>
            </div>
          </div>
        </div>

        <div class="section">
          <h2>Oportunidades para {_v19_escape(t)}</h2>
          <table>
            <thead>
              <tr>
                <th>Ticker</th>
                <th>Estrategia</th>
                <th>Decisión</th>
                <th class="num">Score</th>
                <th class="num">Prima/Precio</th>
                <th>Calidad</th>
                <th>Falta</th>
                <th>Operable</th>
                <th>Acción</th>
              </tr>
            </thead>
            <tbody>
              {_v19_top_rows_html(top, limit=30)}
            </tbody>
          </table>
        </div>

        <div class="footer">
          <a href="/dashboard_decision">Volver al dashboard</a>
        </div>
      </div>
    </body>
    </html>
    """
    return html

@app.get("/gpt_decision_summary")
def gpt_decision_summary():
    data = _v19_safe_data()
    summary = data.get("summary", {}) or {}
    nba = data.get("next_best_action") or {}
    freshness = _v19_freshness(data)
    call = _v19_market_call(data)

    top_3 = []
    for row in (data.get("top", []) or [])[:3]:
        top_3.append({
            "ticker": row.get("ticker"),
            "strategy": row.get("strategy"),
            "decision": row.get("decision"),
            "score": row.get("score"),
            "price": row.get("price"),
            "can_operate": row.get("can_operate"),
            "missing_confirmations": row.get("missing_confirmations"),
            "recommendation": row.get("recommendation"),
            "reason": row.get("reason"),
        })

    return {
        "engine": "V19_OPERATIONAL_TRADING_DASHBOARD",
        "status": "OK" if data.get("health", {}).get("snapshot_available") else "NO_SNAPSHOT",
        "freshness": freshness,
        "market_call": call.get("market_call"),
        "can_operate_now": call.get("can_operate_now"),
        "summary": summary,
        "best_opportunity": {
            "ticker": nba.get("ticker"),
            "strategy": nba.get("strategy"),
            "decision": nba.get("decision"),
            "score": nba.get("score"),
            "price": nba.get("price"),
            "can_operate": nba.get("can_operate"),
            "missing_confirmations": nba.get("missing_confirmations"),
            "recommendation": nba.get("recommendation"),
            "reason": nba.get("reason"),
        } if nba else None,
        "executive_conclusion": data.get("recommendation") or call.get("message"),
        "top_3": top_3,
        "health": data.get("health", {}),
    }

@app.get("/system_status")
def system_status():
    data = _v19_safe_data()
    freshness = _v19_freshness(data)
    health = data.get("health", {}) or {}

    return {
        "engine": "V19_OPERATIONAL_TRADING_DASHBOARD",
        "api_status": "OK",
        "snapshot_status": "OK" if health.get("snapshot_available") else "NO_SNAPSHOT",
        "remote_ingested": bool(health.get("remote_ingested")),
        "rows_captured": health.get("rows_captured", 0),
        "can_operate_count": health.get("can_operate_count", 0),
        "generated_at": data.get("generated_at"),
        "remote_ingested_at": data.get("remote_ingested_at"),
        "freshness": freshness,
        "summary": data.get("summary", {}),
        "urls": {
            "dashboard": "/dashboard_decision",
            "gpt_summary": "/gpt_decision_summary",
            "system_status": "/system_status",
            "ticker_example": "/dashboard_ticker/QQQ",
        },
    }
'''

if "V19 OPERATIONAL TRADING DASHBOARD" not in m:
    m = m.rstrip() + "\n\n" + v19_block + "\n"

main.write_text(m)
