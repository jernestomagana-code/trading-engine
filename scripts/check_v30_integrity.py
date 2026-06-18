#!/usr/bin/env python3
"""Run local V30 integrity checks for Stock Ultimus."""

from __future__ import annotations

import py_compile
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
RUNTIME_DIR = ROOT / "runtime"
V29_MASTER_SNAPSHOT = RUNTIME_DIR / "v28_master_snapshot.json"
SANITIZED_RUNTIME_FIXTURE = ROOT / "fixtures" / "runtime" / "v28_master_snapshot_sanitized.json"
COMPILE_CANDIDATES = [
    ROOT / "ibkr_bridge.py",
    ROOT / "app" / "main.py",
    ROOT / "tmp_v30_patch" / "ibkr_bridge.py",
    ROOT / "tmp_v30_patch" / "app" / "main.py",
    ROOT / "strategy_rules.py",
    ROOT / "scripts" / "validate_v30_fixtures.py",
    ROOT / "scripts" / "smoke_v29_endpoints.py",
    ROOT / "scripts" / "check_strategy_research_rules.py",
    ROOT / "scripts" / "check_legacy_compat_endpoints.py",
    ROOT / "scripts" / "check_v32_outcomes_tracking.py",
    ROOT / "scripts" / "check_v31_canonical_paths.py",
    ROOT / "scripts" / "validate_strategy_signal_contract.py",
    ROOT / "scripts" / "validate_tradingview_pine_scripts.py",
    ROOT / "scripts" / "check_strategy_signal_contexts.py",
    ROOT / "scripts" / "sanitize_runtime_snapshot.py",
    ROOT / "scripts" / "validate_runtime_privacy.py",
]
REQUIRED_OPTION = {
    "strike": 180.0,
    "expiration": "2026-07-17",
    "dte": 39,
    "bid": 1.2,
    "ask": 1.35,
    "mid": 1.275,
    "spread": 0.15,
    "spread_pct": 11.76,
    "delta": -0.28,
}


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def run_fixture_guard() -> list[str]:
    script = ROOT / "scripts" / "validate_v30_fixtures.py"
    result = subprocess.run(
        [PYTHON, str(script)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode == 0:
        print(result.stdout.strip())
        return []

    output = "\n".join(part for part in [result.stdout.strip(), result.stderr.strip()] if part)
    return [output or "fixture guard failed without output"]


def run_endpoint_smoke() -> list[str]:
    script = ROOT / "scripts" / "smoke_v29_endpoints.py"
    result = subprocess.run(
        [PYTHON, str(script)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode == 0:
        print(result.stdout.strip())
        return []

    output = "\n".join(part for part in [result.stdout.strip(), result.stderr.strip()] if part)
    return [output or "endpoint smoke failed without output"]


def run_strategy_rule_guard() -> list[str]:
    script = ROOT / "scripts" / "check_strategy_research_rules.py"
    result = subprocess.run(
        [PYTHON, str(script)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode == 0:
        print(result.stdout.strip())
        return []

    output = "\n".join(part for part in [result.stdout.strip(), result.stderr.strip()] if part)
    return [output or "strategy rule guard failed without output"]


def run_v31_canonical_guard() -> list[str]:
    script = ROOT / "scripts" / "check_v31_canonical_paths.py"
    result = subprocess.run(
        [PYTHON, str(script)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode == 0:
        print(result.stdout.strip())
        return []

    output = "\n".join(part for part in [result.stdout.strip(), result.stderr.strip()] if part)
    return [output or "v31 canonical guard failed without output"]


def run_legacy_compatibility_guard() -> list[str]:
    script = ROOT / "scripts" / "check_legacy_compat_endpoints.py"
    result = subprocess.run(
        [PYTHON, str(script)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode == 0:
        print(result.stdout.strip())
        return []

    output = "\n".join(part for part in [result.stdout.strip(), result.stderr.strip()] if part)
    return [output or "legacy compatibility guard failed without output"]


def run_v32_outcomes_guard() -> list[str]:
    script = ROOT / "scripts" / "check_v32_outcomes_tracking.py"
    result = subprocess.run(
        [PYTHON, str(script)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode == 0:
        print(result.stdout.strip())
        return []

    output = "\n".join(part for part in [result.stdout.strip(), result.stderr.strip()] if part)
    return [output or "v32 outcomes guard failed without output"]


def run_runtime_privacy_guard() -> list[str]:
    script = ROOT / "scripts" / "validate_runtime_privacy.py"
    result = subprocess.run(
        [PYTHON, str(script)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode == 0:
        print(result.stdout.strip())
        return []

    output = "\n".join(part for part in [result.stdout.strip(), result.stderr.strip()] if part)
    return [output or "runtime privacy guard failed without output"]


def run_strategy_signal_contract_guard() -> list[str]:
    script = ROOT / "scripts" / "validate_strategy_signal_contract.py"
    result = subprocess.run(
        [PYTHON, str(script)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode == 0:
        print(result.stdout.strip())
        return []

    output = "\n".join(part for part in [result.stdout.strip(), result.stderr.strip()] if part)
    return [output or "strategy signal contract guard failed without output"]


def run_tradingview_pine_guard() -> list[str]:
    script = ROOT / "scripts" / "validate_tradingview_pine_scripts.py"
    result = subprocess.run(
        [PYTHON, str(script)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode == 0:
        print(result.stdout.strip())
        return []

    output = "\n".join(part for part in [result.stdout.strip(), result.stderr.strip()] if part)
    return [output or "TradingView Pine guard failed without output"]


def run_strategy_signal_context_guard() -> list[str]:
    script = ROOT / "scripts" / "check_strategy_signal_contexts.py"
    result = subprocess.run(
        [PYTHON, str(script)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode == 0:
        print(result.stdout.strip())
        return []

    output = "\n".join(part for part in [result.stdout.strip(), result.stderr.strip()] if part)
    return [output or "strategy signal context guard failed without output"]


def compile_available_files() -> list[str]:
    errors: list[str] = []
    compiled = 0
    skipped = []

    for path in COMPILE_CANDIDATES:
        if not path.exists():
            skipped.append(rel(path))
            continue
        try:
            cache_file = Path(tempfile.gettempdir()) / "stock_ultimus_pycache" / rel(path).replace("/", "_")
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            py_compile.compile(str(path), cfile=str(cache_file) + ".pyc", doraise=True)
            compiled += 1
        except py_compile.PyCompileError as exc:
            errors.append(f"{rel(path)}: {exc.msg}")

    print(f"Compiled {compiled} Python files.")
    if skipped:
        print("Skipped missing files: " + ", ".join(skipped))

    return errors


def load_app_module():
    sys.dont_write_bytecode = True
    app_path = ROOT / "app" / "main.py"
    spec = importlib.util.spec_from_file_location("stock_ultimus_app_for_v30_check", app_path)
    if spec is None:
        raise RuntimeError("unable to import app/main.py")

    module = importlib.util.module_from_spec(spec)
    module.__dict__["__file__"] = str(app_path)
    source = "from __future__ import annotations\n" + app_path.read_text()
    exec(compile(source, str(app_path), "exec"), module.__dict__)
    return module


def option_row(**overrides):
    row = {
        "ticker": "AAPL",
        "strategy": "NAKED_PUT",
        "decision": "ENTRY",
        "score": 90,
        "price": 185.0,
        "data_quality": "FULL_WITH_GREEKS",
        "risk": {"passes": True},
        **REQUIRED_OPTION,
    }
    row.update(overrides)
    return row


def master_snapshot(row, *, technical_score=85, market_open=True, options_expected=True, technical_overrides=None):
    technical = {
        "ticker": "AAPL",
        "trend": "BULLISH",
        "score": technical_score,
        "technical_score": technical_score,
    }
    if technical_overrides:
        technical.update(technical_overrides)

    return {
        "source": "V30_INTEGRITY_TEST",
        "generated_at": "2026-06-09T00:00:00+00:00",
        "options_rows": [row],
        "technical_snapshot": {
            "AAPL": technical
        },
        "market": {
            "is_regular_market_open": market_open,
            "options_bidask_expected": options_expected,
            "label": "INTEGRITY_TEST",
        },
    }


def run_v29_engine_case(app_module, name, snapshot, expected_state, expected_blocker=None):
    V29_MASTER_SNAPSHOT.write_text(json.dumps(snapshot, indent=2, sort_keys=True))
    result = app_module._v29_decide_ticker("AAPL")
    state = result.get("final_state")
    blocker = result.get("main_blocker")

    if state != expected_state:
        return f"{name}: expected {expected_state}, got {state} ({blocker})"
    if expected_blocker is not None and blocker != expected_blocker:
        return f"{name}: expected blocker {expected_blocker}, got {blocker}"
    if state != "ENTRY_READY" and result.get("can_operate") is True:
        return f"{name}: can_operate must be false for {state}"

    return None


def run_v29_engine_guard() -> list[str]:
    failures: list[str] = []
    backup = V29_MASTER_SNAPSHOT.read_text() if V29_MASTER_SNAPSHOT.exists() else None

    try:
        RUNTIME_DIR.mkdir(exist_ok=True)
        app_module = load_app_module()

        cases = [
            (
                "complete_entry_ready",
                master_snapshot(option_row()),
                "ENTRY_READY",
                None,
            ),
            (
                "technical_confirmed_incomplete_options_market_closed",
                master_snapshot(option_row(delta=None), market_open=False, options_expected=False),
                "WAIT_OPTIONS_DATA",
                "MISSING_BID_ASK_SPREAD_OR_CONTRACT_QUALITY",
            ),
            (
                "risk_blocked",
                master_snapshot(option_row(risk={"passes": False, "blocker": "RISK_RULE_FAILED"})),
                "RISK_BLOCKED",
                "RISK_RULE_FAILED",
            ),
            (
                "risk_not_confirmed",
                master_snapshot(option_row(risk={})),
                "RISK_BLOCKED",
                "RISK_NOT_CONFIRMED",
            ),
            (
                "wait_technical",
                master_snapshot(option_row(), technical_score=40),
                "WAIT_TECHNICAL",
                "TECHNICAL_NOT_CONFIRMED",
            ),
            (
                "event_risk_blocked",
                master_snapshot(option_row(), technical_overrides={"event_risk": True}),
                "RISK_BLOCKED",
                "EVENT_RISK_ACTIVE",
            ),
            (
                "earnings_blocked",
                master_snapshot(option_row(), technical_overrides={"earnings_soon": True}),
                "RISK_BLOCKED",
                "EARNINGS_SOON",
            ),
            (
                "liquidity_blocked_volume",
                master_snapshot(option_row(volume=10, open_interest=400)),
                "RISK_BLOCKED",
                "LOW_OPTION_VOLUME",
            ),
            (
                "liquidity_blocked_open_interest",
                master_snapshot(option_row(volume=100, open_interest=50)),
                "RISK_BLOCKED",
                "LOW_OPEN_INTEREST",
            ),
            (
                "canslim_blocked",
                master_snapshot(option_row(), technical_overrides={"canslim": {"passes": False, "score": 42}}),
                "RISK_BLOCKED",
                "CANSLIM_BLOCKED",
            ),
            (
                "manual_review_blocked",
                master_snapshot(option_row(manual_review_required=True)),
                "MANUAL_REVIEW_BLOCKED",
                "MANUAL_REVIEW_REQUIRED",
            ),
        ]

        for name, snapshot, expected_state, expected_blocker in cases:
            failure = run_v29_engine_case(app_module, name, snapshot, expected_state, expected_blocker)
            if failure:
                failures.append(failure)

    except Exception as exc:
        failures.append(f"V29 engine guard failed to run: {exc}")
    finally:
        if backup is None:
            try:
                V29_MASTER_SNAPSHOT.unlink()
            except FileNotFoundError:
                pass
        else:
            V29_MASTER_SNAPSHOT.write_text(backup)

    if not failures:
        print("Validated V29 engine guard scenarios.")

    return failures


def run_sanitized_runtime_fixture_guard() -> list[str]:
    failures: list[str] = []
    backup = V29_MASTER_SNAPSHOT.read_text() if V29_MASTER_SNAPSHOT.exists() else None

    try:
        if not SANITIZED_RUNTIME_FIXTURE.exists():
            return [f"missing sanitized runtime fixture: {rel(SANITIZED_RUNTIME_FIXTURE)}"]

        RUNTIME_DIR.mkdir(exist_ok=True)
        fixture = json.loads(SANITIZED_RUNTIME_FIXTURE.read_text())
        expected = fixture.get("expected_decisions") or {}
        if not expected:
            return [f"{rel(SANITIZED_RUNTIME_FIXTURE)} missing expected_decisions"]

        V29_MASTER_SNAPSHOT.write_text(json.dumps(fixture, indent=2, sort_keys=True))
        app_module = load_app_module()

        for ticker, expectation in sorted(expected.items()):
            result = app_module._v29_decide_ticker(ticker)
            state = result.get("final_state")
            blocker = result.get("main_blocker")
            expected_state = expectation.get("final_state")
            expected_blocker = expectation.get("main_blocker")

            if state != expected_state:
                failures.append(f"sanitized runtime {ticker}: expected {expected_state}, got {state}")
            if blocker != expected_blocker:
                failures.append(f"sanitized runtime {ticker}: expected blocker {expected_blocker}, got {blocker}")
            if state != "ENTRY_READY" and result.get("can_operate") is True:
                failures.append(f"sanitized runtime {ticker}: can_operate must be false for {state}")

    except Exception as exc:
        failures.append(f"sanitized runtime fixture guard failed to run: {exc}")
    finally:
        if backup is None:
            try:
                V29_MASTER_SNAPSHOT.unlink()
            except FileNotFoundError:
                pass
        else:
            V29_MASTER_SNAPSHOT.write_text(backup)

    if not failures:
        print(f"Validated sanitized runtime fixture for {len(expected)} tickers.")

    return failures


def main() -> int:
    failures: list[str] = []
    failures.extend(run_fixture_guard())
    failures.extend(compile_available_files())
    failures.extend(run_runtime_privacy_guard())
    failures.extend(run_strategy_signal_contract_guard())
    failures.extend(run_tradingview_pine_guard())
    failures.extend(run_strategy_signal_context_guard())
    failures.extend(run_strategy_rule_guard())
    failures.extend(run_legacy_compatibility_guard())
    failures.extend(run_v32_outcomes_guard())
    failures.extend(run_v31_canonical_guard())
    failures.extend(run_v29_engine_guard())
    failures.extend(run_sanitized_runtime_fixture_guard())
    failures.extend(run_endpoint_smoke())

    if failures:
        print("\nV30 integrity check failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("V30 integrity check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
