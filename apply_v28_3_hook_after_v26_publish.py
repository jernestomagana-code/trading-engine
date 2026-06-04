from pathlib import Path
import re

BRIDGE = Path("ibkr_bridge.py")
s = BRIDGE.read_text()

Path("ibkr_bridge_backup_before_v28_3_hook_after_v26_publish.py").write_text(s)

# Quitar intentos anteriores V28.1 / V28.2 para evitar ruido
s = re.sub(
    r'\n# ============================================================\n# V28\.1 FORCE OFFICIAL V28 PUBLISHER.*?# ============================================================\n# END V28\.1 FORCE OFFICIAL V28 PUBLISHER\n# ============================================================\n',
    '\n',
    s,
    flags=re.S
)

s = re.sub(
    r'\n# ============================================================\n# V28\.2 OFFICIAL V28 AUTO PUBLISHER.*?# ============================================================\n# END V28\.2 OFFICIAL V28 AUTO PUBLISHER - ORDER SAFE\n# ============================================================\n',
    '\n',
    s,
    flags=re.S
)

s = re.sub(
    r'\n\s*# V28\.[12] AUTO OFFICIAL PUBLISH CALL.*?print\(f"V28\.[12].*?\n',
    '\n',
    s,
    flags=re.S
)

# Bloque V28.3: definido al inicio del archivo para que exista antes del ciclo
publisher = r'''
# ============================================================
# V28.3 OFFICIAL PUBLISHER HOOKED AFTER V26
# ============================================================

from pathlib import Path as _v283_Path
from datetime import datetime as _v283_datetime, timezone as _v283_timezone
import os as _v283_os
import json as _v283_json

try:
    import requests as _v283_requests
except Exception:
    _v283_requests = None

_V283_REMOTE_BASE_URL = _v283_os.environ.get(
    "TRADING_ENGINE_REMOTE_URL",
    "https://trading-engine-p097.onrender.com"
).rstrip("/")

_V283_INGEST_URL = _V283_REMOTE_BASE_URL + "/v28_ingest_snapshot"

def _v283_now():
    return _v283_datetime.now(_v283_timezone.utc).isoformat()

def _v283_float(x, default=None):
    try:
        if x is None:
            return default
        return float(x)
    except Exception:
        return default

def _v283_load_runtime_jsons():
    runtime = _v283_Path("runtime")
    out = {}
    if not runtime.exists():
        return out

    for p in runtime.glob("*.json"):
        try:
            out[p.name] = _v283_json.loads(p.read_text())
        except Exception:
            pass
    return out

def _v283_extract_options_rows(data):
    rows = []

    def scan(obj):
        if isinstance(obj, dict):
            # Detectar filas de opciones
            ticker = str(obj.get("ticker") or obj.get("symbol") or "").upper().strip()
            strategy = obj.get("strategy") or obj.get("strategy_hint") or obj.get("best_strategy")
            decision = obj.get("decision") or obj.get("final_decision") or obj.get("state")
            quality = obj.get("data_quality") or obj.get("quality")

            if ticker and (strategy or decision or quality or obj.get("can_operate") is not None):
                r = dict(obj)
                r["ticker"] = ticker
                r["strategy"] = str(strategy or "UNKNOWN").upper()
                r["decision"] = str(decision or "RADAR").upper()
                r["score"] = _v283_float(
                    r.get("score") or r.get("combined_score") or r.get("master_score") or r.get("options_score"),
                    0
                )
                r["price"] = _v283_float(
                    r.get("price") or r.get("premium") or r.get("option_price") or r.get("mid"),
                    None
                )
                r["data_quality"] = quality or "UNKNOWN"
                if "can_operate" not in r:
                    r["can_operate"] = r["decision"] in ["ENTRY", "ENTRY_READY", "OPERAR"]
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
                    for x in v:
                        if isinstance(x, dict):
                            rows.append(dict(x))

            for v in obj.values():
                if isinstance(v, (dict, list)):
                    scan(v)

        elif isinstance(obj, list):
            for x in obj:
                scan(x)

    for v in data.values():
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
        r["score"] = _v283_float(r.get("score") or r.get("combined_score") or r.get("master_score") or r.get("options_score"), 0)
        r["price"] = _v283_float(r.get("price") or r.get("premium") or r.get("option_price") or r.get("mid"), None)
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

def _v283_extract_technical(data):
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
                item["trend"] = str(
                    item.get("trend") or item.get("bias") or item.get("technical_bias") or "UNKNOWN"
                ).upper()
                item["score"] = _v283_float(item.get("technical_score") or item.get("score"), None)
                tech[ticker] = item

            for k, v in obj.items():
                if isinstance(v, dict):
                    scan(v, k)
                elif isinstance(v, list):
                    scan(v, None)

        elif isinstance(obj, list):
            for x in obj:
                scan(x, parent_key)

    for v in data.values():
        scan(v)

    return tech

def _v283_publish_to_v28():
    if _v283_requests is None:
        print("V28.3 OFFICIAL V28 PUBLISH SKIPPED | requests unavailable")
        return

    runtime_data = _v283_load_runtime_jsons()
    rows = _v283_extract_options_rows(runtime_data)
    tech = _v283_extract_technical(runtime_data)

    payload = {
        "source": "IBKR_BRIDGE_V28_3_OFFICIAL_AFTER_V26",
        "generated_at": _v283_now(),
        "options_rows": rows,
        "technical_snapshot": tech,
        "market": {
            "status": "REGULAR_OPTIONS_SESSION",
            "label": "Mercado abierto: opciones en ventana operable",
            "is_regular_market_open": True,
            "options_bidask_expected": True,
            "source": "IBKR_BRIDGE_V28_3_OFFICIAL_AFTER_V26",
            "generated_at": _v283_now()
        },
        "bridge_status": "LIVE_IBKR_AFTER_V26_PUBLISH",
        "runtime_files_seen": sorted(list(runtime_data.keys()))
    }

    try:
        resp = _v283_requests.post(_V283_INGEST_URL, json=payload, timeout=20)
        ok = 200 <= resp.status_code < 300
        print(
            "V28.3 OFFICIAL V28 SNAPSHOT PUBLISHED"
            f" | ok:{ok}"
            f" | status:{resp.status_code}"
            f" | rows:{len(rows)}"
            f" | technical:{len(tech)}"
        )
    except Exception as e:
        print(f"V28.3 OFFICIAL V28 SNAPSHOT ERROR | {e}")

# ============================================================
# END V28.3 OFFICIAL PUBLISHER HOOKED AFTER V26
# ============================================================
'''

if "V28.3 OFFICIAL PUBLISHER HOOKED AFTER V26" not in s:
    # Insertar después de imports iniciales, antes de ejecución principal
    lines = s.splitlines()
    insert_at = 0
    for i, line in enumerate(lines[:300]):
        if line.startswith("import ") or line.startswith("from "):
            insert_at = i + 1
    lines.insert(insert_at, publisher)
    s = "\n".join(lines) + "\n"

# Insertar llamada justo después del print V26 remote publish OK
if "V28.3 HOOK AFTER V26 REMOTE PUBLISH" not in s:
    pattern = r'(?m)^(\s*)print\(f?["\']V26 remote publish OK.*?\n'
    m = re.search(pattern, s)

    if not m:
        pattern = r'(?m)^(\s*)print\(["\']V26 remote publish OK.*?\n'
        m = re.search(pattern, s)

    if m:
        indent = m.group(1)
        call = (
            f"{indent}# V28.3 HOOK AFTER V26 REMOTE PUBLISH\n"
            f"{indent}try:\n"
            f"{indent}    _v283_publish_to_v28()\n"
            f"{indent}except Exception as _v283_hook_error:\n"
            f"{indent}    print(f\"V28.3 hook error: {{_v283_hook_error}}\")\n"
        )
        s = s[:m.end()] + call + s[m.end():]
    else:
        # Fallback: antes de NUEVO CICLO
        pattern2 = r'(?m)^(\s*)print\(["\']NUEVO CICLO'
        m2 = re.search(pattern2, s)
        if m2:
            indent = m2.group(1)
            call = (
                f"{indent}# V28.3 HOOK AFTER V26 REMOTE PUBLISH - FALLBACK\n"
                f"{indent}try:\n"
                f"{indent}    _v283_publish_to_v28()\n"
                f"{indent}except Exception as _v283_hook_error:\n"
                f"{indent}    print(f\"V28.3 hook error: {{_v283_hook_error}}\")\n"
            )
            s = s[:m2.start()] + call + s[m2.start():]
        else:
            print("WARNING: no se encontró ubicación para hook V28.3")

BRIDGE.write_text(s)
print("V28.3 hook after V26 publish applied.")
