from pathlib import Path

bridge = Path("ibkr_bridge.py")
main = Path("app/main.py")

s = bridge.read_text()
m = main.read_text()

# ============================================================
# 1) Subir versión visual
# ============================================================

s = s.replace("V18_OPERATIONAL_DECISION_API", "V18_1_REMOTE_SNAPSHOT_INGEST")
m = m.replace("V18_OPERATIONAL_DECISION_API", "V18_1_REMOTE_SNAPSHOT_INGEST")

# ============================================================
# 2) Agregar helper en bridge para postear snapshot a Render
# ============================================================

remote_bridge_block = r'''
# ============================================================
# SUPER ENGINE BOLSA — V18.1 REMOTE SNAPSHOT INGEST CLIENT
# ============================================================

import os as _v18_1_os
import urllib.request as _v18_1_urllib_request
import urllib.error as _v18_1_urllib_error

V18_1_REMOTE_INGEST_URL = _v18_1_os.getenv(
    "DECISION_DESK_INGEST_URL",
    "https://trading-engine-p097.onrender.com/decision_desk/ingest"
)

V18_1_INGEST_TOKEN = _v18_1_os.getenv("DECISION_DESK_INGEST_TOKEN", "")

def v18_1_post_decision_snapshot(payload):
    """
    V18.1:
    Envía el snapshot generado localmente por ibkr_bridge.py hacia Render,
    para que /decision_desk, /decision_desk/{ticker} y /decision_desk/health
    puedan mostrar datos reales.
    """
    try:
        if not payload or not isinstance(payload, dict):
            return {"posted": False, "reason": "empty_payload"}

        body = _v18_json.dumps(payload, ensure_ascii=False).encode("utf-8")

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "SuperEngineBolsa-V18.1",
        }

        if V18_1_INGEST_TOKEN:
            headers["X-Decision-Desk-Token"] = V18_1_INGEST_TOKEN

        req = _v18_1_urllib_request.Request(
            V18_1_REMOTE_INGEST_URL,
            data=body,
            headers=headers,
            method="POST",
        )

        with _v18_1_urllib_request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
            return {
                "posted": True,
                "status": getattr(resp, "status", None),
                "response": raw[:300],
            }

    except Exception as e:
        return {
            "posted": False,
            "error": str(e),
            "url": V18_1_REMOTE_INGEST_URL,
        }
'''

if "V18.1 REMOTE SNAPSHOT INGEST CLIENT" not in s:
    marker = "# ============================================================\n# SUPER ENGINE BOLSA — V18 OPERATIONAL DECISION API HELPERS"
    idx = s.find(marker)

    if idx == -1:
        marker = "# ============================================================\n# SUPER ENGINE BOLSA — V18_1_REMOTE_SNAPSHOT_INGEST HELPERS"
        idx = s.find(marker)

    if idx != -1:
        s = s[:idx] + remote_bridge_block + "\n" + s[idx:]
    else:
        s = remote_bridge_block + "\n" + s

# ============================================================
# 3) Después de guardar snapshot local, postearlo a Render
# ============================================================

old = 'v18_payload = v18_write_decision_snapshot(V17_SUMMARY_ROWS)'
new = '''v18_payload = v18_write_decision_snapshot(V17_SUMMARY_ROWS)
            v18_remote = v18_1_post_decision_snapshot(v18_payload)'''

if old in s and "v18_1_post_decision_snapshot(v18_payload)" not in s:
    s = s.replace(old, new, 1)

old_print = '''print(f"NEXT: {nba.get('ticker')} | {nba.get('strategy')} | {nba.get('decision')} | can_operate:{nba.get('can_operate')}")'''
new_print = '''print(f"NEXT: {nba.get('ticker')} | {nba.get('strategy')} | {nba.get('decision')} | can_operate:{nba.get('can_operate')}")
                try:
                    print(f"REMOTE INGEST: {v18_remote.get('posted')} | status:{v18_remote.get('status')} | url:{v18_remote.get('url', '')}")
                except Exception:
                    pass'''

if old_print in s and "REMOTE INGEST:" not in s:
    s = s.replace(old_print, new_print, 1)

# ============================================================
# 4) Agregar endpoint POST /decision_desk/ingest en app/main.py
# ============================================================

remote_api_block = r'''
# ============================================================
# SUPER ENGINE BOLSA — V18.1 REMOTE SNAPSHOT INGEST ENDPOINT
# ============================================================

from fastapi import Request as _v18_1_Request, Header as _v18_1_Header
import os as _v18_1_api_os

_V18_1_API_INGEST_TOKEN = _v18_1_api_os.getenv("DECISION_DESK_INGEST_TOKEN", "")

@app.post("/decision_desk/ingest")
async def decision_desk_ingest(
    request: _v18_1_Request,
    x_decision_desk_token: str | None = _v18_1_Header(default=None)
):
    """
    Recibe desde ibkr_bridge.py el snapshot operativo generado localmente
    y lo guarda en Render para que los endpoints GET lo puedan leer.
    """
    try:
        if _V18_1_API_INGEST_TOKEN:
            if x_decision_desk_token != _V18_1_API_INGEST_TOKEN:
                return {
                    "engine": "V18_1_REMOTE_SNAPSHOT_INGEST",
                    "status": "UNAUTHORIZED",
                    "saved": False,
                }

        payload = await request.json()

        if not isinstance(payload, dict):
            return {
                "engine": "V18_1_REMOTE_SNAPSHOT_INGEST",
                "status": "INVALID_PAYLOAD",
                "saved": False,
            }

        payload["remote_ingested_at"] = _v18_api_datetime.now(_v18_api_timezone.utc).isoformat()
        payload["snapshot_available"] = True

        try:
            payload.setdefault("health", {})
            payload["health"]["snapshot_available"] = True
            payload["health"]["remote_ingested"] = True
        except Exception:
            pass

        save_path = _v18_api_Path("runtime/decision_desk_snapshot.json")
        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_path.write_text(_v18_api_json.dumps(payload, ensure_ascii=False, indent=2))

        return {
            "engine": "V18_1_REMOTE_SNAPSHOT_INGEST",
            "status": "OK",
            "saved": True,
            "generated_at": payload.get("generated_at"),
            "summary": payload.get("summary"),
            "next_best_action": payload.get("next_best_action"),
            "rows_captured": payload.get("health", {}).get("rows_captured"),
        }

    except Exception as e:
        return {
            "engine": "V18_1_REMOTE_SNAPSHOT_INGEST",
            "status": "ERROR",
            "saved": False,
            "error": str(e),
        }
'''

if "V18.1 REMOTE SNAPSHOT INGEST ENDPOINT" not in m:
    m = m.rstrip() + "\n\n" + remote_api_block + "\n"

bridge.write_text(s)
main.write_text(m)
