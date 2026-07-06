#!/usr/bin/env python3
"""Build a local static dashboard from Stock Ultimus runtime reports."""

from __future__ import annotations

import argparse
import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
DEFAULT_OUT = RUNTIME / "local_environment_dashboard.html"


REPORTS = [
    ("market_open_readiness", "Market Open Readiness", "market_open_readiness_latest.json"),
    ("market_open_checklist", "Market Open Checklist", "market_open_checklist_latest.json"),
    ("tradingview_bundle", "TradingView Bundle", "tradingview_alert_bundle_health.json"),
    ("post_open_monitor", "Post Open Monitor", "post_open_monitor_latest.json"),
    ("environment_auth", "Environment Auth", "environment_auth_check_latest.json"),
    ("branch_pr_readiness", "Branch / PR Readiness", "branch_pr_readiness_latest.json"),
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path) -> dict[str, Any]:
    try:
        if path.exists():
            payload = json.loads(path.read_text())
            return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}
    return {}


def status_of(payload: dict[str, Any]) -> str:
    for key in ["alert_level", "status", "state"]:
        value = payload.get(key)
        if value is not None:
            return str(value)
    if payload.get("ok") is True:
        return "OK"
    if payload.get("ok") is False:
        return "ACTION_REQUIRED"
    return "MISSING"


def status_class(status: str) -> str:
    text = status.upper()
    if text in {"OK", "READY", "READY_FOR_MANUAL_REVIEW", "READY_FOR_EVIDENCE", "PARAMETER_REVIEW_READY"}:
        return "good"
    if "WAIT" in text or text in {"WATCH", "WARN", "PASS_WITH_WARNINGS"}:
        return "watch"
    if "MISSING" in text:
        return "missing"
    return "action"


def compact_summary(name: str, payload: dict[str, Any]) -> list[tuple[str, Any]]:
    if not payload:
        return [("available", False)]
    if name == "market_open_readiness":
        tv = payload.get("tradingview_bundle") if isinstance(payload.get("tradingview_bundle"), dict) else {}
        return [
            ("next", payload.get("next_required_action")),
            ("TV e2e", tv.get("real_e2e_confirmed")),
            ("TV received", f"{tv.get('total_received_required_event_count')}/{tv.get('total_required_alert_count')}"),
            ("IBKR", payload.get("ibkr_primary_gap")),
            ("gate", payload.get("operational_gate_state")),
        ]
    if name == "post_open_monitor":
        summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
        return [
            ("next", payload.get("next_required_action")),
            ("actions", summary.get("action_count")),
            ("watches", summary.get("watch_count")),
            ("IBKR", summary.get("ibkr_primary_gap")),
        ]
    if name == "environment_auth":
        checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
        return [(key, (value or {}).get("ok")) for key, value in checks.items()]
    if name == "tradingview_bundle":
        return [
            ("coverage", payload.get("coverage_valid")),
            ("real e2e", payload.get("real_e2e_confirmed")),
            ("expected", payload.get("total_expected_alert_count")),
            ("quarantine", payload.get("total_quarantine_event_count")),
        ]
    if name == "branch_pr_readiness":
        return [
            ("branch", payload.get("branch")),
            ("clean", payload.get("clean_worktree")),
            ("ahead", payload.get("ahead")),
            ("behind", payload.get("behind")),
        ]
    return [("version", payload.get("check_version") or payload.get("monitor_version") or payload.get("engine"))]


def load_reports(runtime_dir: Path) -> list[dict[str, Any]]:
    rows = []
    for name, title, filename in REPORTS:
        path = runtime_dir / filename
        payload = read_json(path)
        status = status_of(payload)
        rows.append(
            {
                "name": name,
                "title": title,
                "path": str(path),
                "available": bool(payload),
                "status": status,
                "summary": compact_summary(name, payload),
                "payload": payload,
            }
        )
    return rows


def render_dashboard(rows: list[dict[str, Any]], *, generated_at: str) -> str:
    cards = []
    for row in rows:
        summary = "".join(
            "<li><span>{}</span><strong>{}</strong></li>".format(
                html.escape(str(key)),
                html.escape(str(value)),
            )
            for key, value in row["summary"]
        )
        cards.append(
            """
            <article class="card {klass}">
              <header><h2>{title}</h2><span>{status}</span></header>
              <ul>{summary}</ul>
              <p>{path}</p>
            </article>
            """.format(
                klass=status_class(row["status"]),
                title=html.escape(row["title"]),
                status=html.escape(row["status"]),
                summary=summary,
                path=html.escape(row["path"]),
            )
        )
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Stock Ultimus Local Environment</title>
  <style>
    :root {{ color-scheme: light; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    body {{ margin: 0; background: #f6f7f8; color: #17202a; }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 28px; }}
    header.page {{ display: flex; justify-content: space-between; gap: 20px; align-items: flex-end; margin-bottom: 22px; }}
    h1 {{ margin: 0; font-size: 30px; letter-spacing: 0; }}
    .stamp {{ color: #5b6470; font-size: 13px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(290px, 1fr)); gap: 14px; }}
    .card {{ background: #fff; border: 1px solid #d9dee5; border-left: 6px solid #6b7280; border-radius: 8px; padding: 16px; min-height: 190px; }}
    .card.good {{ border-left-color: #15803d; }}
    .card.watch {{ border-left-color: #ca8a04; }}
    .card.action {{ border-left-color: #b91c1c; }}
    .card.missing {{ border-left-color: #6b7280; opacity: .72; }}
    .card header {{ display: flex; justify-content: space-between; gap: 12px; align-items: center; margin-bottom: 12px; }}
    h2 {{ margin: 0; font-size: 16px; }}
    .card header span {{ font-size: 12px; font-weight: 700; text-transform: uppercase; color: #111827; }}
    ul {{ list-style: none; padding: 0; margin: 0; display: grid; gap: 8px; }}
    li {{ display: flex; justify-content: space-between; gap: 12px; border-bottom: 1px solid #eef0f3; padding-bottom: 6px; }}
    li span {{ color: #667085; }}
    li strong {{ text-align: right; font-size: 13px; }}
    p {{ margin: 14px 0 0; color: #6b7280; font-size: 12px; overflow-wrap: anywhere; }}
  </style>
</head>
<body>
  <main>
    <header class="page">
      <div>
        <h1>Stock Ultimus Local Environment</h1>
        <div class="stamp">Decision support only. No automated execution.</div>
      </div>
      <div class="stamp">Generated {generated_at}</div>
    </header>
    <section class="grid">
      {cards}
    </section>
  </main>
</body>
</html>
""".format(generated_at=html.escape(generated_at), cards="\n".join(cards))


def build_dashboard(runtime_dir: Path = RUNTIME, *, generated_at: str | None = None) -> dict[str, Any]:
    generated_at = generated_at or now_iso()
    rows = load_reports(runtime_dir)
    html_text = render_dashboard(rows, generated_at=generated_at)
    return {
        "engine": "STOCK_ULTIMUS_LOCAL_ENVIRONMENT_DASHBOARD_BUILDER",
        "generated_at": generated_at,
        "report_count": len(rows),
        "available_report_count": sum(1 for row in rows if row["available"]),
        "rows": rows,
        "html": html_text,
        "execution_authorized": False,
        "not_order_instruction": True,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build local Stock Ultimus environment dashboard.")
    parser.add_argument("--runtime-dir", default=str(RUNTIME))
    parser.add_argument("--output", default=str(DEFAULT_OUT))
    parser.add_argument("--json-out", default=str(RUNTIME / "local_environment_dashboard_latest.json"))
    parser.add_argument("--no-write", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = build_dashboard(Path(args.runtime_dir))
    if not args.no_write:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(payload["html"], encoding="utf-8")
        json_out = Path(args.json_out)
        json_out.parent.mkdir(parents=True, exist_ok=True)
        redacted = dict(payload)
        redacted.pop("html", None)
        json_out.write_text(json.dumps(redacted, indent=2, sort_keys=True, default=str) + "\n")
    print(json.dumps({k: v for k, v in payload.items() if k != "html" and k != "rows"}, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
