from pathlib import Path
import re

BRIDGE = Path("ibkr_bridge.py")
s = BRIDGE.read_text()

Path("ibkr_bridge_backup_before_v28_2_fix_publisher_order.py").write_text(s)

# ============================================================
# 1) LIMPIAR V28.1 MAL INSERTADO
# ============================================================

s = re.sub(
    r'\n# ============================================================\n# V28\.1 FORCE OFFICIAL V28 PUBLISHER.*?# ============================================================\n# END V28\.1 FORCE OFFICIAL V28 PUBLISHER\n# ============================================================\n',
    '\n',
    s,
    flags=re.S
)

s = re.sub(
    r'\n\s*# V28\.1 AUTO OFFICIAL PUBLISH CALL\n\s*try:\n\s*_v281_publish_official_v28_snapshot\(\)\n\s*except Exception as _v281_pub_error:\n\s*print\(f"V28\.1 official publish call error: \{_v281_pub_error\}"\)\n',
    '\n',
    s,
    flags=re.S
)

s = re.sub(
    r'\n# V28\.1 AUTO OFFICIAL PUBLISH CALL - EOF FALLBACK\ntry:\n\s*_v281_publish_official_v28_snapshot\(\)\nexcept Exception as _v281_pub_error:\n\s*print\(f"V28\.1 official publish call error: \{_v281_pub_error\}"\)\n',
    '\n',
    s,
    flags=re.S
)

# ============================================================
# 2) NUEVO BLOQUE V28.2 BIEN UBICADO
# ============================================================

publisher = r'''
# ============================================================
# V28.2 OFFICIAL V28 AUTO PUBLISHER - ORDER SAFE
# ============================================================

from pathlib import Path as _v282_Path
from datetime import datetime as _v282_datetime, timezone as _v282_timezone
import os as _v282_os
import json as _v282_json

try:
    import requests as _v282_requests
except Exception:
    _v282_requests = None

_V282_REMOTE_BASE_URL = _v282_os.environ.get(
    "TRADING_ENGINE_REMOTE_URL",
    "https://trading-engine-p097.onrender.com"
).rstrip("/")

_V282_INGEST_URL = _V282_REMOTE_BASE_URL + "/v28_ingest_snapshot"

def _v282_now():
    return _v282_datetime.now(_v282_timezone.utc).isoformat()

def _v282_safe_float(x, default=None):
    try:
        if x is None:
            return default
        return float(x)
    except Exception:
        return default

def _v282_load_runtime_jsons():
    out = {}
    runtime = _v282_Path("runtime")
    if not runtime.exists():
        return out

    for p in runtime.glob("*.json"):
        try:
            out[p.name] = _v282_json.loads(p.read_text())
        except Exception:
            pass

    return out

def _v282_find_options_rows(data):
    rows = []

    def scan(obj):
        if isinstance(obj, list):
            for item in obj:
                scan(item)

        elif isinstance(obj, dict):
            ticker = str(obj.get("ticker") or obj.get("symbol") or "").upper().strip()
            strategy = obj.get("strategy") or obj.get("strategy_hint") or obj.get("best_strategy")
            decision = obj.get("decision") or obj.get("final_decision") or obj.get("state")

            looks_like_option = bool(
                ticker
                and (
                    strategy
                    or decision
                    or obj.get("option_symbol")
                    or obj.get("strike")
                    or obj.get("expiration")
                    or obj.get("data_quality")
                    or obj.get("can_operate") is not None
                )
            )

            if looks_like_option:
                r = dict(obj)
                r["ticker"] = ticker
                r["strategy"] = str(strategy or "UNKNOWN").upper()
                r["decision"] = str(decision or "RADAR").upper()
                r["score"] = r.get("score") or r.get("combined_score") or r.get("master_score") or r.get("options_score") or 0
                r["price"] = r.get("price") or r.get("premium") or r.get("option_price") or r.get("mid")
                r["data_quality"] = r.get("data_quality") or r.get("quality") or "UNKNOWN"
                rows.append(r)

            for key in [
                "options_rows",
                "rows",
                "top",
                "top_5",
                "sample_rows",
                "best_rows",
                "entry_candidates",
                "radar_candidates"
            ]:
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
        ticker = str(r.get("ticker") or r.get("symbol") or "").upper().strip()
        if not ticker:
            continue

        strategy = str(r.get("strategy") or r.get("strategy_hint") or "UNKNOWN").upper()
        decision = str(r.get("decision") or r.get("final_decision") or "RADAR").upper()

        r["ticker"] = ticker
        r["strategy"] = strategy
        r["decision"] = decision
        r["score"] = _v282_safe_float(r.get("score") or r.get("combined_score") or r.get("master_score") or r.get("options_score"), 0)
        r["price"] = _v282_safe_float(r.get("price") or r.get("premium") or r.get("option_price") or r.get("mid"), None)
        r["data_quality"] = r.get("data_quality") or r.get("quality") or "UNKNOWN"

        if "can_operate" not in r:
            r["can_operate"] = decision in ["ENTRY", "ENTRY_READY", "OPERAR"]

        key = (
            ticker,
            strategy,
            decision,
            str(r.get("price")),
            str(r.get("strike")),
            str(r.get("expiration")),
        )

        if key not in seen:
            seen.add(key)
            cleaned.append(r)

    return cleaned

def _v282_find_technical_snapshot(data):
    tech = {}

    def scan(obj, parent_key=None):
        if isinstance(obj, dict):
            ticker = str(obj.get("ticker") or obj.get("symbol") or parent_key or "").upper().strip()

            looks_technical = any(k in obj for k in [
                "trend",
                "bias",
                "technical_bias",
                "rsi",
                "adx",
                "vwap_position",
                "volume_relative",
                "support_near",
                "resistance_near",
                "range_breakout",
                "event_risk",
                "technical_score",
                "score"
            ])

            if ticker and looks_technical:
                item = dict(obj)
                item["ticker"] = ticker
                item["trend"] = str(item.get("trend") or item.get("bias") or item.get("technical_bias") or "UNKNOWN").upper()
                item["score"] = _v282_safe_float(item.get("technical_score") or item.get("score"), None)
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

def _v282_publish_official_v28_snapshot():
    if _v282_requests is None:
        print("V28.2 OFFICIAL V28 PUBLISH SKIPPED | requests not available")
        return {"ok": False, "error": "requests_not_available"}

    runtime_data = _v282_load_runtime_jsons()
    rows = _v282_find_options_rows(runtime_data)
    tech = _v282_find_technical_snapshot(runtime_data)

    payload = {
        "source": "IBKR_BRIDGE_V28_2_OFFICIAL_PUBLISHER",
        "generated_at": _v282_now(),
        "options_rows": rows,
        "technical_snapshot": tech,
        "market": {
            "status": "REGULAR_OPTIONS_SESSION",
            "label": "Mercado abierto: opciones en ventana operable",
            "is_regular_market_open": True,
            "options_bidask_expected": True,
            "source": "IBKR_BRIDGE_V28_2_OFFICIAL_PUBLISHER",
            "generated_at": _v282_now()
        },
        "bridge_status": "LIVE_IBKR_AUTO_PUBLISHED",
        "runtime_files_seen": sorted(list(runtime_data.keys()))
    }

    try:
        resp = _v282_requests.post(_V282_INGEST_URL, json=payload, timeout=20)
        ok = 200 <= resp.status_code < 300

        print(
            "V28.2 OFFICIAL V28 SNAPSHOT PUBLISHED"
            f" | ok:{ok}"
            f" | status:{resp.status_code}"
            f" | rows:{len(rows)}"
            f" | technical:{len(tech)}"
            f" | url:{_V282_INGEST_URL}"
        )

        return {
            "ok": ok,
            "status": resp.status_code,
            "rows": len(rows),
            "technical": len(tech),
            "text": resp.text[:300]
        }

    except Exception as e:
        print(f"V28.2 OFFICIAL V28 SNAPSHOT ERROR | {e}")
        return {"ok": False, "error": str(e)}

# ============================================================
# END V28.2 OFFICIAL V28 AUTO PUBLISHER - ORDER SAFE
# ============================================================
'''

if "V28.2 OFFICIAL V28 AUTO PUBLISHER - ORDER SAFE" not in s:
    # Insertar antes de que empiece la conexión principal a IBKR.
    markers = [
        'print("Conectando a IBKR',
        "print('Conectando a IBKR",
        'print("Conectando a IBKR...',
        "print('Conectando a IBKR...",
        'ib.connect(',
    ]

    inserted = False

    for marker in markers:
        idx = s.find(marker)
        if idx != -1:
            s = s[:idx] + publisher + "\n\n" + s[idx:]
            inserted = True
            break

    if not inserted:
        # Fallback seguro: después de imports iniciales.
        lines = s.splitlines()
        insert_at = 0
        for i, line in enumerate(lines[:250]):
            if line.startswith("import ") or line.startswith("from "):
                insert_at = i + 1
        lines.insert(insert_at, publisher)
        s = "\n".join(lines) + "\n"

# ============================================================
# 3) INSERTAR LLAMADA AUTOMÁTICA DESPUÉS DE CREAR SNAPSHOT
# ============================================================

if "V28.2 AUTO OFFICIAL PUBLISH CALL" not in s:
    patterns = [
        r'(?m)^(\s*)print\(["\']V18 DECISION API SNAPSHOT UPDATED',
        r'(?m)^(\s*)print\(["\']V26 remote publish OK',
        r'(?m)^(\s*)print\(["\']NUEVO CICLO',
        r'(?m)^(\s*)ib\.sleep\(',
    ]

    inserted = False

    for pat in patterns:
        m = re.search(pat, s)
        if m:
            indent = m.group(1)
            call = (
                f"{indent}# V28.2 AUTO OFFICIAL PUBLISH CALL\n"
                f"{indent}try:\n"
                f"{indent}    _v282_publish_official_v28_snapshot()\n"
                f"{indent}except Exception as _v282_pub_error:\n"
                f"{indent}    print(f\"V28.2 official publish call error: {{_v282_pub_error}}\")\n"
            )
            insert_pos = m.end()
            line_end = s.find("\n", insert_pos)
            if line_end == -1:
                line_end = insert_pos
            s = s[:line_end+1] + call + s[line_end+1:]
            inserted = True
            break

    if not inserted:
        s += """

# V28.2 AUTO OFFICIAL PUBLISH CALL - EOF FALLBACK
try:
    _v282_publish_official_v28_snapshot()
except Exception as _v282_pub_error:
    print(f"V28.2 official publish call error: {_v282_pub_error}")
"""

BRIDGE.write_text(s)
print("V28.2 publisher order fix applied safely.")
