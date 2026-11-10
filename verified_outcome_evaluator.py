"""Capture-based paper markouts. Never infer fills, quote clocks or missing legs."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import hashlib
import json
import math
import console_market_calendar as calendar

VERSION = 'verified_paper_markout_v2'
NY = ZoneInfo('America/New_York')
CHECKPOINTS = {'EOD': 0, 'PLUS_1D': 1, 'PLUS_5D': 5}


def instant(value):
    try:
        result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return result.astimezone(timezone.utc) if result.tzinfo else None
    except (ValueError, TypeError):
        return None


def number(value):
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def identity(row):
    if not isinstance(row, dict):
        return None
    if str(row.get('sec_type') or row.get('secType') or '').upper() == 'STK':
        con_id = row.get('contract_con_id') or row.get('con_id') or row.get('conId')
        if con_id and row.get('currency'):
            return str(con_id), '99999999', 'STK', 0.0, 1.0, str(row['currency']).upper()
        return None
    expiry = str(row.get('expiration') or row.get('expiry') or '').replace('-', '')
    right = str(row.get('right') or '').upper()
    right = {'PUT':'P', 'CALL':'C'}.get(right, right)
    con_id = row.get('contract_con_id') or row.get('con_id') or row.get('conId')
    strike, multiplier = number(row.get('strike')), number(row.get('multiplier'))
    currency = row.get('currency')
    if not con_id or len(expiry) != 8 or right not in ('P','C') or strike is None or not multiplier or multiplier <= 0 or not currency:
        return None
    try:
        datetime.strptime(expiry, '%Y%m%d')
    except ValueError:
        return None
    return str(con_id), expiry, right, strike, multiplier, str(currency).upper()


def clock(row):
    return instant(row.get('quote_timestamp') or row.get('quote_received_at'))


def reference(row):
    return row.get('observation_ref') or row.get('capture_id')


def quotes(row):
    bid, ask = number(row.get('bid')), number(row.get('ask'))
    return (bid, ask) if bid is not None and ask is not None and 0 <= bid <= ask and ask > 0 else None


def checkpoint_at(entry, checkpoint):
    if checkpoint not in CHECKPOINTS:
        return None
    day = entry.astimezone(NY).date()
    if not calendar.trading_day(day):
        return None
    for _ in range(CHECKPOINTS[checkpoint]):
        day += timedelta(days=1)
        while not calendar.trading_day(day):
            day += timedelta(days=1)
    hour = 13 if day.isoformat() in calendar.EARLY_CLOSES else 16
    return datetime(day.year, day.month, day.day, hour, tzinfo=NY).astimezone(timezone.utc)


def evaluate(outcome, rows, checkpoint='EOD', now=None):
    now = now or datetime.now(timezone.utc)
    original = deepcopy(outcome)
    def fail(reason, status='NOT_EVALUATED'):
        return dict(status=status, reason=reason, outcome=original, execution_authorized=False, not_order_instruction=True)
    if outcome.get('outcome') != 'PENDING':
        return fail('OUTCOME_NOT_PENDING', 'SKIPPED')
    entry = instant(outcome.get('entry_ready_at') or outcome.get('recorded_at'))
    if not entry or entry > now:
        return fail('ENTRY_CLOCK_MISSING_OR_FUTURE')
    due = checkpoint_at(entry, checkpoint)
    if due is None:
        return fail('INVALID_CHECKPOINT_OR_ENTRY_SESSION')
    if now < due:
        return fail('CHECKPOINT_NOT_DUE')
    if entry >= due:
        return fail('ENTRY_AFTER_CHECKPOINT')
    contract = outcome.get('selected_contract') or {}
    if not isinstance(contract, dict):
        return fail('INVALID_CONTRACT_RECORD')
    legs = outcome.get('legs') or contract.get('legs')
    if not legs:
        # A covered call includes stock, and spreads require every leg.
        side = {'NAKED_PUT':'SELL', 'CASH_SECURED_PUT':'SELL', 'LONG_CALL':'BUY', 'LONG_PUT':'BUY'}.get(str(outcome.get('strategy')).upper())
        if not side:
            return fail('COMPLETE_STRATEGY_LEGS_REQUIRED')
        legs = [dict(contract, side=side, quantity=outcome.get('quantity', 1))]
    if not isinstance(legs, list) or not legs or not all(isinstance(leg, dict) for leg in legs):
        return fail('COMPLETE_STRATEGY_LEGS_REQUIRED')
    required_count = {'IRON_CONDOR':4, 'IRON_FLY':4, 'BULL_PUT_SPREAD':2,
                      'BEAR_CALL_SPREAD':2, 'COVERED_CALL':2}.get(str(outcome.get('strategy')).upper())
    if required_count and len(legs) != required_count:
        return fail('COMPLETE_STRATEGY_LEGS_REQUIRED')
    if any(leg.get('synthetic') is True for leg in legs):
        return fail('SYNTHETIC_ENTRY_CAPTURE')
    measurements = []
    seen = set()
    gross = 0.0
    for leg in legs:
        key = identity(leg)
        if not key or key in seen:
            return fail('INCOMPLETE_OR_DUPLICATE_CONTRACT_IDENTITY')
        seen.add(key)
        entry_quote, entry_clock = quotes(leg), clock(leg)
        if not entry_quote or not entry_clock or not reference(leg):
            return fail('ENTRY_CAPTURE_EVIDENCE_MISSING')
        if not 0 <= (entry-entry_clock).total_seconds() <= 120:
            return fail('ENTRY_QUOTE_STALE_OR_FUTURE')
        if due.astimezone(NY).strftime('%Y%m%d') > key[1]:
            return fail('CHECKPOINT_AFTER_EXPIRY_REQUIRES_SETTLEMENT_EVIDENCE')
        candidates = [r for r in rows if r.get('synthetic') is not True and identity(r) == key and clock(r) and reference(r) and quotes(r)
                      and 0 <= (due-clock(r)).total_seconds() <= 300 and clock(r) > entry]
        if not candidates:
            return fail('EXACT_CONTRACT_CHECKPOINT_QUOTE_MISSING')
        current = max(candidates, key=clock)
        side, qty = str(leg.get('side')).upper(), number(leg.get('quantity'))
        if side not in ('BUY','SELL') or qty is None or qty <= 0 or not qty.is_integer():
            return fail('POSITION_SIDE_OR_QUANTITY_INVALID')
        entry_price = entry_quote[1] if side == 'BUY' else entry_quote[0]
        exit_price = quotes(current)[0] if side == 'BUY' else quotes(current)[1]
        pnl = (exit_price-entry_price)*(1 if side == 'BUY' else -1)*qty*key[4]
        if side == 'SELL' and entry_price <= 0:
            return fail('ENTRY_SELL_BID_NOT_EXECUTABLE')
        gross += pnl
        measurements.append(dict(contract_identity=list(key), side=side, quantity=qty,
            entry_price=entry_price, exit_price=exit_price, gross_pnl=pnl,
            entry_observation_ref=reference(leg), current_observation_ref=reference(current),
            entry_quote_timestamp=entry_clock.isoformat(), quote_timestamp=clock(current).isoformat()))
    if len({m['contract_identity'][5] for m in measurements}) != 1:
        return fail('MIXED_CURRENCIES_REQUIRE_FX_EVIDENCE')
    quote_times = [instant(m['quote_timestamp']) for m in measurements]
    if (max(quote_times)-min(quote_times)).total_seconds() > 30:
        return fail('LEG_QUOTES_NOT_SYNCHRONIZED')
    fees = number(outcome.get('round_trip_commission'))
    if fees is None or fees < 0:
        return fail('ROUND_TRIP_COMMISSION_MISSING')
    risk = number(outcome.get('risk_basis_dollars'))
    cashflows = number(outcome.get('cashflows_dollars'))
    if any(m['contract_identity'][2]=='STK' for m in measurements) and cashflows is None:
        return fail('STOCK_CASHFLOW_EVIDENCE_REQUIRED')
    net = round(gross-fees+(cashflows or 0), 6)
    key = hashlib.sha256(json.dumps([outcome.get('outcome_id') or outcome.get('id'),checkpoint,due.isoformat(),measurements,fees],sort_keys=True).encode()).hexdigest()
    previous = [e for e in outcome.get('auto_evaluations',[]) if e.get('outcome_evaluation_version') == VERSION]
    if any(e.get('checkpoint') == checkpoint for e in previous):
        return fail('CHECKPOINT_ALREADY_EVALUATED', 'SKIPPED')
    ev = dict(outcome_evaluation_version=VERSION, evaluation_id=key, checkpoint=checkpoint,
        checkpoint_at=due.isoformat(), evaluated_at=now.isoformat(), legs=measurements,
        gross_pnl=round(gross,6), round_trip_commission=fees, cashflows_dollars=cashflows or 0, net_pnl=net,
        current_paper_pnl_r=round(net/risk,6) if risk and risk>0 else None,
        risk_basis_dollars=risk if risk and risk>0 else None,
        currency=measurements[0]['contract_identity'][5], paper_outcome=True,
        valuation_basis='ENTRY_EXECUTABLE_SIDE_EXIT_LIQUIDATION_SIDE',
        not_order_instruction=True, execution_authorized=False)
    original.update(auto_evaluations=list(outcome.get('auto_evaluations',[]))+[ev], latest_auto_evaluation=ev,
                    current_paper_pnl_r=ev['current_paper_pnl_r'], current_paper_pnl=net,
                    outcome_engine_version=VERSION, evaluated_at=now.isoformat(),
                    outcome_auto_evaluation_status='EVALUATED', paper_outcome=True,
                    execution_authorized=False, not_order_instruction=True)
    # Discrete markouts are not continuous MFE/MAE and are not closed trades.
    for name in ('mfe_r','mae_r'):
        original.pop(name, None)
    return dict(status='EVALUATED', outcome=original, evaluation=ev,
                execution_authorized=False, not_order_instruction=True)
