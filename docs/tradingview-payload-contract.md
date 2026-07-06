# TradingView Payload Contract

This contract feeds the Stock Ultimus TradingView signal ledger. It records
technical evidence only; it does not authorize trades or change strategy rules.

## Endpoint

Use the deployed backend TradingView/technical webhook:

```text
POST https://<backend-host>/technical_snapshot
```

Recommended header when enabled:

```text
X-Webhook-Secret: <WEBHOOK_SECRET>
Content-Type: application/json
```

## Required Fields

- `ticker`
- `timeframe`
- `strategy_context`
- `price`
- `session_state`
- `vwap`
- `opening_range_high`
- `opening_range_low`
- `breakout_direction`
- `adx`
- `atr`
- `volume_relative`
- `premarket_high`
- `premarket_low`
- `major_event_window`
- `risk_daily_status`
- `portfolio_status`

Optional but recommended:

- `event`
- `event_code`
- `action`
- `vwap_position`
- `invalidation`
- `logical_stop`
- `logical_target`
- `source`

## TradingView Alert Message Template

Paste this as the alert message, then make sure the plotted names match the
indicator script names exactly.

```json
{
  "action": "ALERT_ONLY",
  "adx": "{{plot(\"ADX\")}}",
  "atr": "{{plot(\"ATR\")}}",
  "breakout_direction": "LONG",
  "event": "ORB_VWAP_BREAKOUT",
  "event_code": "MNQ_ORB_LONG_V1",
  "invalidation": "VWAP_LOST",
  "logical_stop": "{{plot(\"STOP\")}}",
  "logical_target": "{{plot(\"TARGET\")}}",
  "major_event_window": "NONE",
  "portfolio_status": "OK",
  "premarket_high": "{{plot(\"PMH\")}}",
  "premarket_low": "{{plot(\"PML\")}}",
  "price": "{{close}}",
  "risk_daily_status": "OK",
  "session_state": "OPENING_RANGE",
  "source": "TRADINGVIEW",
  "strategy_context": "INTRADAY_INDEX_FUTURES",
  "ticker": "{{ticker}}",
  "timeframe": "{{interval}}",
  "volume_relative": "{{plot(\"RVOL\")}}",
  "vwap": "{{plot(\"VWAP\")}}",
  "vwap_position": "ABOVE",
  "opening_range_high": "{{plot(\"ORH\")}}",
  "opening_range_low": "{{plot(\"ORL\")}}"
}
```

## Local Validation

Validate the concrete sample:

```bash
python3 scripts/validate_tradingview_payload.py --payload docs/tradingview_payload_sample.json --strict
```

Print and validate the TradingView placeholder template:

```bash
python3 scripts/validate_tradingview_payload.py --template
```

Append a valid sample to the local ledger for a local smoke test:

```bash
python3 scripts/validate_tradingview_payload.py --payload docs/tradingview_payload_sample.json --append-ledger
```

The append command writes `runtime/v32_signal_events.json`. It is a local ledger
test only and still reports `execution_authorized=false`.

## Operational Checks

After the first real alert arrives:

```bash
python3 scripts/run_foundation_health_check.py --no-write
python3 scripts/run_operational_evidence_gate.py --no-write
```

Expected improvement:

- TradingView ledger moves from `WAITING_FOR_DATA` to `OK`.
- Operational Evidence Gate removes `NO_TRADINGVIEW_LEDGER_EVENTS`.
- The engine remains manual-review only.
