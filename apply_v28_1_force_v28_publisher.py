from pathlib import Path
import re

BRIDGE = Path("ibkr_bridge.py")
s = BRIDGE.read_text()

Path("ibkr_bridge_backup_before_v28_1_force_publisher.py").write_text(s)

# 1) Insertar publisher V28 oficial si no existe
publisher = r'''

# ============================================================
# V28.1 FORCE OFFICIAL V28 PUBLISHER
# ============================================================
import os as _v281_os
import json as _v281_json
from datetime import datetime as _v281_datetime, timezone as _v281_timezone

try:
    import requests as _v281_requests
except Exception:
    _v281_requests = None

_V281_REMOTE_BASE_URL = _v281_os.environ.get(
    "TRADING_ENGINE_REMOTE_URL",
    "https://trading-engine-p097.onrender.com"
).rstrip("/")

_V281_INGEST_URL = _V281_REMOTE_BASE_URL + "/v28_ingest_snapshot"

def _v281_now():
    return _v281_datetime.now(_v281_timezone.utc).isoformat()

def _v281_load_runtime_jsons():
    out = {}
    runtime = Path("runtime")
    if not runtime.exists():
        return out

    for p in runtime.glob("*.json"):
        try:
            out[p.name] = _v281_json.loads(p.read_text())
        except Exception:
            pass
    return out

def _v281_find_options_rows(data):
    rows = []

    def scan(obj):
        if isinstance(obj, list):
            for x in obj:
                scan(x)
        elif isinstance(obj, dict):
            looks_like_row = (
                obj.get("ticker")
                and (
                    obj.get("strategy")
                    or obj.get("strategy_hint")
                    or obj.get("decision")
                    or obj.get("score")
                )
            )
            if looks_like_row:
                rows.append(dict(obj))

            for key in ["options_rows", "rows", "top", "top_5", "sample_rows", "best_rows"]:
                v = obj.get(key)
                if isinstance(v, list):
                    for r in v:
                        if isinstance(r, dict):
                            rows.append(dict(r))

            for v in obj.values():
                if isinstance(v, (dict, list)):
                    scan(v)

    for _, v in data.items():
        scan(v)

    cleaned = []
    seen = set()
    for r in rows:
        ticker = str(r.get("ticker") or "").upper().strip()
        if not ticker:
            continue

        strategy = str(r.get("strategy") or r.get("strategy_hint") or r.get("best_strategy") or "UNKNOWN").upper()
        decision = str(r.get("decision") or r.get("final_decision") or r.get("state") or "RADAR").upper()

        r["ticker"] = ticker
        r["strategy"] = strategy
        r["decision"] = decision
        r["score"] = r.get("score") or r.get("combined_score") or r.get("master_score") or r.get("options_score")
        r["price"] = r.get("price") or r.get("premium") or r.get("option_price") or r.get("mid")
        r["data_quality"] = r.get("data_quality") or r.get("quality") or "UNKNOWN"

        key = (ticker, strategy, decision, str(r.get("price")))
        if key not in seen:
            seen.add(key)
            cleaned.append(r)

    return cleaned

def _v281_find_technical(data):
    tech = {}

    def scan(obj, parent_key=None):
        if isinstance(obj, dict):
            ticker = str(obj.get("ticker") or parent_key or "").upper().strip()
            looks_technical = any(k in obj for k in [
                "trend", "bias", "rsi", "adx", "vwap_position",
                "volume_relative", "support_near", "resistance_near", "score"
            ])

            if ticker and looks_technical:
                item = dict(obj)
                item["ticker"] = ticker
                tech[ticker] = item

            for k, v in obj.items():
                if isinstance(v, dict):
                    scan(v, k)
                elif isinstance(v, list):
                    scan(v, None)

        elif isinstance(obj, list):
            for x in obj:
                scan(x, parent_key)

    for _, v in data.items():
        scan(v)

    return tech

def _v281_publish_official_v28_snapshot():
    if _v281_requests is None:
        print("V28.1 OFFICIAL PUBLISH SKIPPED | requests not available")
        return {"ok": False, "error": "requests_not_available"}

    runtime_data = _v281_load_runtime_jsons()
    rows = _v281_find_options_rows(runtime_data)
    tech = _v281_find_technical(runtime_data)

    payload = {
        "source": "IBKR_BRIDGE_V28_1_OFFICIAL_PUBLISHER",
        "generated_at": _v281_now(),
        "options_rows": rows,
        "technical_snapshot": tech,
        "market": {
            "status": "REGULAR_OPTIONS_SESSION",
            "label": "Mercado abierto: opciones en ventana operable",
            "is_regular_market_open": True,
            "options_bidask_expected": True,
            "source": "IBKR_BRIDGE_V28_1_OFFICIAL_PUBLISHER",
            "generated_at": _v281_now()
        },
        "bridge_status": "LIVE_IBKR_AUTO_PUBLISHED",
        "runtime_files_seen": sorted(list(runtime_data.keys()))
    }

    try:
        resp = _v281_requests.post(_V281_INGEST_URL, json=payload, timeout=15)
        ok = 200 <= resp.status_code < 300
        print(
            "V28.1 OFFICIAL V28 SNAPSHOT PUBLISHED"
            f" | ok:{ok}"
            f" | status:{resp.status_code}"
            f" | rows:{len(rows)}"
            f" | technical:{len(tech)}"
            f" | url:{_V281_INGEST_URL}"
        )
        return {
            "ok": ok,
            "status": resp.status_code,
            "rows": len(rows),
            "technical": len(tech),
            "text": resp.text[:300]
        }
    except Exception as e:
        print(f"V28.1 OFFICIAL V28 SNAPSHOT ERROR | {e}")
        return {"ok": False, "error": str(e)}
# ============================================================
# END V28.1 FORCE OFFICIAL V28 PUBLISHER
# ============================================================
'''

if "V28.1 FORCE OFFICIAL V28 PUBLISHER" not in s:
    s = s.rstrip() + "\n\n" + publisher + "\n"

# 2) Insertar llamada automática antes de cada nuevo ciclo si no existe
if "V28.1 AUTO OFFICIAL PUBLISH CALL" not in s:
    patterns = [
        r'(?m)^(\s*)print\(["\']NUEVO CICLO',
        r'(?m)^(\s*)print\(["\']=+',
        r'(?m)^(\s*)ib\.sleep\(',
        r'(?m)^(\s*)time\.sleep\(',
    ]

    inserted = False
    for pat in patterns:
        m = re.search(pat, s)
        if m:
            indent = m.group(1)
            call = (
                f"{indent}# V28.1 AUTO OFFICIAL PUBLISH CALL\n"
                f"{indent}try:\n"
                f"{indent}    _v281_publish_official_v28_snapshot()\n"
                f"{indent}except Exception as _v281_pub_error:\n"
                f"{indent}    print(f\"V28.1 official publish call error: {{_v281_pub_error}}\")\n"
            )
            s = s[:m.start()] + call + s[m.start():]
            inserted = True
            break

    if not inserted:
        s += """
# V28.1 AUTO OFFICIAL PUBLISH CALL - EOF FALLBACK
try:
    _v281_publish_official_v28_snapshot()
except Exception as _v281_pub_error:
    print(f"V28.1 official publish call error: {_v281_pub_error}")
"""

BRIDGE.write_text(s)
print("V28.1 official V28 publisher patch applied.")
