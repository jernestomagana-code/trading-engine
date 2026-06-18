# Strategy Signal Contracts

Version: `strategy_signal_contract_v1`

Stock Ultimus receives TradingView strategy signals as technical snapshots. These
signals are inputs to deterministic decision logic; they never authorize an
order. `ENTRY_READY` means ready for manual review only.

## Preferred Endpoint

POST technical alerts to:

```text
/technical_snapshot
```

The app also exposes helper endpoints:

```text
/strategy_signal_contract
/strategy_signal_template?ticker=QQQ&strategy_context=NAKED_PUT
```

Local fixtures live in:

```text
fixtures/tradingview/
```

Validate them with:

```bash
python3 scripts/validate_strategy_signal_contract.py
```

## Required Fields

Every TradingView strategy alert should include:

- `ticker`
- `timeframe`
- `strategy_context`
- `trend`
- `score`

Accepted `strategy_context` values:

- `NAKED_PUT`
- `CASH_SECURED_PUT`
- `COVERED_CALL`
- `IRON_CONDOR`
- `FUTURES`
- `CANSLIM_FILTER`

## Recommended Fields

Use these fields when a Pine script can produce them:

- `rsi`
- `adx`
- `support_near`
- `resistance_near`
- `range_20d`
- `range_breakout`
- `vwap_position`
- `volume_relative`
- `iv_rank`
- `earnings_soon`
- `event_risk`
- `canslim`
- `canslim_score`
- `canslim_passes`

## Strategy Interpretation

`NAKED_PUT` and `CASH_SECURED_PUT` should confirm bullish or constructive
technical context, preferably near support and without event risk.

`COVERED_CALL` should confirm neutral, extended, resistance-near, or
management-oriented context. It should not be treated as the same signal as a
new bullish entry.

`IRON_CONDOR` should confirm range, neutral trend, lower ADX, acceptable RSI,
and adequate implied volatility context.

`FUTURES` should remain a separate intraday technical context. CANSLIM is not
applicable to futures.

## CANSLIM Filter

CANSLIM is a separate fundamental/growth filter, not a replacement for technical
confirmation, option executable data, risk rules, or manual review.

Accepted payload shapes:

```json
{
  "ticker": "AAPL",
  "timeframe": "1d",
  "strategy_context": "NAKED_PUT",
  "trend": "bullish",
  "score": 72,
  "canslim": {
    "passes": true,
    "score": 78,
    "rating": "PASS"
  }
}
```

```json
{
  "ticker": "AAPL",
  "timeframe": "1d",
  "strategy_context": "NAKED_PUT",
  "trend": "bullish",
  "score": 72,
  "canslim_passes": true,
  "canslim_score": 78
}
```

If CANSLIM data is missing, V29 records it as `NOT_PROVIDED` and does not block
current behavior. If CANSLIM data is provided and fails, the decision is blocked
as `RISK_BLOCKED` with `CANSLIM_BLOCKED` or `CANSLIM_SCORE_BELOW_MIN`.

## Example TradingView Alert Payload

```json
{
  "ticker": "{{ticker}}",
  "timeframe": "{{interval}}",
  "strategy_context": "NAKED_PUT",
  "trend": "bullish",
  "score": 72,
  "rsi": 52,
  "adx": 18,
  "support_near": true,
  "resistance_near": false,
  "range_20d": false,
  "range_breakout": false,
  "vwap_position": "near",
  "volume_relative": 1.0,
  "iv_rank": 45,
  "earnings_soon": false,
  "event_risk": false,
  "canslim": {
    "passes": true,
    "score": 78,
    "rating": "PASS"
  },
  "source": "TRADINGVIEW_STRATEGY_SIGNAL",
  "contract_version": "strategy_signal_contract_v1"
}
```

## Guardrails

- Do not include broker credentials, account identifiers, tokens, balances, or
  position-level private data in TradingView alerts.
- Do not use alert text to override deterministic blocker logic.
- Do not let CANSLIM, GPT, dashboard copy, or TradingView labels bypass
  `WAIT_OPTIONS_DATA`, risk blockers, or manual review.
- No alert may place or authorize live orders.
