#!/usr/bin/env python3
"""Guard research-backed strategy readiness rules."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_app_module():
    sys.dont_write_bytecode = True
    app_path = ROOT / "app" / "main.py"
    spec = importlib.util.spec_from_file_location("stock_ultimus_app_for_strategy_rules", app_path)
    if spec is None:
        raise RuntimeError("unable to import app/main.py")

    module = importlib.util.module_from_spec(spec)
    module.__dict__["__file__"] = str(app_path)
    source = "from __future__ import annotations\n" + app_path.read_text()
    exec(compile(source, str(app_path), "exec"), module.__dict__)
    return module


def technical_context(
    *,
    alignment="bullish",
    support=False,
    resistance=False,
    state="RANGE",
    priority=85,
    event_risk=False,
    earnings_soon=False,
    rsi=50,
    adx=18,
    range_20d=True,
    range_breakout=False,
    iv_rank=50,
):
    return {
        "available": True,
        "classification": {
            "alignment": alignment,
            "priority_score": priority,
            "state": state,
            "latest_data": {
                "support_near": support,
                "resistance_near": resistance,
                "event_risk": event_risk,
                "earnings_soon": earnings_soon,
                "rsi": rsi,
                "adx": adx,
                "range_20d": range_20d,
                "range_breakout": range_breakout,
                "iv_rank": iv_rank,
            },
        },
    }


def naked_put_ibkr(*, delta=-0.18, dte=39, iv=0.30, mid=1.0, data_quality="FULL_WITH_GREEKS", decision="OPERAR"):
    return {
        "available": True,
        "option_strategy_hint": "NAKED_PUT",
        "option_type": "PUT",
        "option_dte": dte,
        "option_delta": delta,
        "option_iv": iv,
        "option_mid": mid,
        "option_data_quality": data_quality,
        "option_decision": decision,
        "latest_price": 200.0,
    }


def covered_call_ibkr(*, delta=0.20, dte=39, iv=0.25, mid=1.0, data_quality="FULL_WITH_GREEKS", decision="OPERAR"):
    return {
        "available": True,
        "position_class": "COVERED_CALL_CANDIDATE",
        "position_size": 100,
        "option_strategy_hint": "COVERED_CALL",
        "option_type": "CALL",
        "option_dte": dte,
        "option_delta": delta,
        "option_iv": iv,
        "option_mid": mid,
        "option_data_quality": data_quality,
        "option_decision": decision,
    }


def iron_condor_ibkr(*, dte=40, delta=0.18, mid=1.0):
    return {
        "available": True,
        "option_dte": dte,
        "option_delta": delta,
        "option_mid": mid,
        "option_data_quality": "FULL_WITH_GREEKS",
        "options_candidates": [
            condor_leg("PUT", dte=dte, delta=delta),
            condor_leg("CALL", dte=dte, delta=delta),
        ],
    }


def condor_leg(option_type, *, bid=1.0, ask=1.15, spread_pct=13.95, delta=0.18, iv=0.30, dte=40):
    mid = round((bid + ask) / 2, 4) if bid is not None and ask is not None else 1.075
    return {
        "ticker": "SPY",
        "strategy_hint": "IRON_CONDOR",
        "option_type": option_type,
        "option_symbol": f"SPY_{option_type}",
        "strike": 500.0 if option_type == "CALL" else 470.0,
        "expiration": "2026-07-17",
        "dte": dte,
        "mid": mid,
        "bid": bid,
        "ask": ask,
        "spread_pct": spread_pct,
        "delta": delta,
        "iv": iv,
        "implied_volatility": iv,
        "data_quality": "FULL_WITH_GREEKS",
        "strategy_decision": "OPERAR",
    }


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def main() -> int:
    app = load_app_module()

    bullish_np = app._evaluate_naked_put_pro_v12(
        "AAPL",
        technical_context(alignment="bullish", support=True),
        naked_put_ibkr(),
        {},
    )
    require(bullish_np.get("decision") == "OPERAR", f"bullish naked put should OPERAR, got {bullish_np}")

    neutral_np = app._evaluate_naked_put_pro_v12(
        "AAPL",
        technical_context(alignment="neutral", support=True),
        naked_put_ibkr(),
        {},
    )
    require(neutral_np.get("decision") != "OPERAR", f"neutral naked put must not OPERAR, got {neutral_np}")
    require(
        any("alcista confirmado" in str(x) for x in neutral_np.get("blockers", [])),
        f"neutral naked put should explain bullish confirmation blocker, got {neutral_np.get('blockers')}",
    )

    base_cc = app._evaluate_covered_call_pro_v12(
        "AAPL",
        technical_context(alignment="bearish", resistance=True, state="EXTENDED_LONG"),
        covered_call_ibkr(),
        {},
    )
    require(base_cc.get("decision") == "OPERAR", f"covered call base case should OPERAR, got {base_cc}")

    earnings_cc = app._evaluate_covered_call_pro_v12(
        "AAPL",
        technical_context(alignment="bearish", resistance=True, state="EXTENDED_LONG", earnings_soon=True),
        covered_call_ibkr(),
        {},
    )
    require(earnings_cc.get("decision") != "OPERAR", f"earnings covered call must not OPERAR, got {earnings_cc}")
    require(
        any("Earnings próximos." == str(x) for x in earnings_cc.get("blockers", [])),
        f"earnings covered call should add earnings blocker, got {earnings_cc.get('blockers')}",
    )

    wide_delta_cc = app._evaluate_covered_call_pro_v12(
        "AAPL",
        technical_context(alignment="bearish", resistance=True, state="EXTENDED_LONG"),
        covered_call_ibkr(delta=0.30),
        {},
    )
    require(wide_delta_cc.get("decision") != "OPERAR", f"0.30 delta covered call must not OPERAR, got {wide_delta_cc}")
    require(
        any("readiness 0.15–0.25" in str(x) for x in wide_delta_cc.get("blockers", [])),
        f"0.30 delta covered call should expose readiness blocker, got {wide_delta_cc.get('blockers')}",
    )

    require(app.option_spread_ok({"spread_pct": 11.76}) is True, "11.76% spread should pass readiness gate")
    require(app.option_spread_ok({"spread_pct": 25.0}) is False, "25% spread should fail readiness gate")

    base_structure = {
        "put_leg": app.compact_option(condor_leg("PUT")),
        "call_leg": app.compact_option(condor_leg("CALL")),
        "estimated_short_credit": 0.6,
        "dte_match": True,
    }
    base_quality = app.iron_condor_quality_gate(base_structure)
    require(base_quality.get("can_operar") is True, f"base iron condor structure should OPERAR, got {base_quality}")

    missing_bidask_structure = {
        **base_structure,
        "call_leg": app.compact_option(condor_leg("CALL", ask=None)),
    }
    missing_bidask_quality = app.iron_condor_quality_gate(missing_bidask_structure)
    require(
        missing_bidask_quality.get("can_operar") is False,
        f"missing bid/ask iron condor leg must fail OPERAR gate, got {missing_bidask_quality}",
    )

    wide_spread_structure = {
        **base_structure,
        "put_leg": app.compact_option(condor_leg("PUT", spread_pct=26.0)),
    }
    wide_spread_quality = app.iron_condor_quality_gate(wide_spread_structure)
    require(
        wide_spread_quality.get("can_operar") is False,
        f"wide-spread iron condor leg must fail OPERAR gate, got {wide_spread_quality}",
    )
    require(
        any("spread supera" in str(x) for x in wide_spread_quality.get("blockers", [])),
        f"wide-spread iron condor should expose spread blocker, got {wide_spread_quality.get('blockers')}",
    )

    low_vix_condor = app._evaluate_iron_condor_pro_v13_1(
        "SPY",
        technical_context(alignment="neutral", iv_rank=50, rsi=50, adx=18, range_20d=True),
        iron_condor_ibkr(),
        {"vix": 15.0},
    )
    require(low_vix_condor.get("decision") != "OPERAR", f"VIX 15 iron condor must not OPERAR, got {low_vix_condor}")
    require(
        any("VIX por debajo del rango de readiness" in str(x) for x in low_vix_condor.get("blockers", [])),
        f"VIX 15 iron condor should expose radar-only blocker, got {low_vix_condor.get('blockers')}",
    )

    print("Validated research-backed strategy readiness rules.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
